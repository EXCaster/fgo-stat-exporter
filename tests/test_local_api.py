import html
import json
import re
import threading
import time

import pytest

from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.local_api import create_app
from fgo_local_exporter.reports import ReportDocument
from fgo_local_exporter.settings import LocalConfig
from fgo_local_exporter.statistics import export_statistics


@pytest.fixture
def capture():
    # 人工构造，不来自游戏账号或登录响应。
    return {
        "response": [{"nid": "login", "resCode": "00", "success": {"token": "test-secret"}}],
        "cache": {
            "serverTime": 1700000000,
            "replaced": {
                "userGame": [
                    {
                        "userId": 123,
                        "friendCode": "123456789012",
                        "name": "人工测试",
                        "lv": 10,
                        "rkchannel": 24,
                        "cookie": "test-secret",
                    }
                ],
                "userSvt": [{"id": 1, "svtId": 800100, "lv": 1, "usk": "test-secret"}],
                "userSvtCollection": [{"svtId": 800100}],
            },
        },
    }


class Builder:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.options = None

    def revision(self):
        return "synthetic-shared-revision"

    def render(self, raw, options, cancel, *, progress=None):
        self.options = options
        if progress is not None:
            progress("images", 1, 3)
        self.entered.set()
        self.release.wait(2)
        data = json.loads(raw)
        name = data["cache"]["replaced"]["userGame"][0]["name"]
        return ReportDocument(
            '<html><body><main class="sheet">'
            + html.escape(name)
            + '<img src="ASSET_BASE/'
            + "a" * 24
            + '.png"></main></body></html>',
            {"a" * 24 + ".png": b"synthetic-png"},
            {"synthetic": True},
            self.revision(),
        )


@pytest.fixture
def app():
    builder = Builder()
    app = create_app(builder=builder, cleanup=False)
    yield app
    builder.release.set()
    app.extensions["local_store"].close()


def visitor(app):
    client = app.test_client()
    root = client.get("/", base_url="http://127.0.0.1:55313")
    csrf = re.search(rb'name="fgo-csrf" content="([^"]+)"', root.data)[1].decode()
    headers = {"Origin": "http://127.0.0.1:55313", "X-FGO-CSRF": csrf}
    return client, headers


def get(client, path):
    return client.get(path, base_url="http://127.0.0.1:55313")


def post(client, path, headers, value):
    return client.post(path, base_url="http://127.0.0.1:55313", headers=headers, json=value)


def import_capture(client, headers, capture):
    response = client.post(
        "/api/import",
        base_url="http://127.0.0.1:55313",
        data=json.dumps(capture).encode(),
        content_type="application/octet-stream",
        headers={**headers, "X-FGO-Consent": "yes", "X-FGO-Server": "ios"},
    )
    assert response.status_code == 200
    return wait_state(client, lambda s: s["phase"] in {"complete", "error"})


def test_mobile_import_uses_same_whitelist_and_loopback_guard(capture):
    from fgo_local_exporter.mobile import bounded_import

    mobile = create_app(importer=bounded_import, mobile=True, cleanup=False)
    try:
        client, headers = visitor(mobile)
        assert "安卓本机版" in get(client, "/").get_data(as_text=True)
        state = import_capture(client, headers, capture)
        assert state["phase"] == "complete"
        raw = get(client, "/api/export").data
        assert b"test-secret" not in raw
        assert json.loads(raw)["cache"]["replaced"]["userGame"][0]["name"] == "人工测试"
        assert client.get("/api/state", base_url="http://192.0.2.1").status_code == 403
    finally:
        mobile.extensions["local_store"].close()


def wait_state(client, condition):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = get(client, "/api/state").json
        if condition(state):
            return state
        time.sleep(0.01)
    pytest.fail("人工测试操作未在时限内完成")


def test_http_guards_cookie_and_cross_site_rejection(app):
    client, headers = visitor(app)
    cookie = client.get_cookie("fgo-visitor", domain="127.0.0.1")
    assert cookie.http_only and cookie.same_site == "Strict"
    assert cookie.value.encode() not in get(client, "/").data
    assert get(app.test_client(), "/api/state").status_code == 401
    assert client.get("/api/state", base_url="http://untrusted.invalid").status_code == 403
    assert get(client, "/api/state").headers["Cache-Control"] == "no-store"
    assert (
        client.get(
            "/", base_url="http://127.0.0.1:55313", headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/state",
            base_url="http://127.0.0.1:55313",
            headers={"Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )
    assert post(client, "/api/clear", {}, {}).status_code == 403
    assert (
        post(
            client, "/api/clear", {**headers, "Origin": "https://untrusted.invalid"}, {}
        ).status_code
        == 403
    )
    assert post(client, "/api/clear", headers, {}).status_code == 200


def test_import_filters_secrets_and_isolates_visitors(app, capture):
    client, headers = visitor(app)
    other, _ = visitor(app)
    state = import_capture(client, headers, capture)
    assert state["phase"] == "complete" and not state["qr_available"]
    exported = get(client, "/api/export")
    expected, _ = export_statistics(capture)
    assert exported.data == expected
    assert b"test-secret" not in exported.data
    assert "attachment" in exported.headers["Content-Disposition"]
    assert get(other, "/api/export").status_code == 409
    assert "userItem" in state["preview"]["missing_tables"]
    assert "saved_export" not in state


def test_report_is_private_and_clear_invalidates_all_outputs(app, capture):
    client, headers = visitor(app)
    other, _ = visitor(app)
    import_capture(client, headers, capture)
    assert (
        post(client, "/api/report", headers, {"friend": False, "support": True}).status_code == 200
    )
    state = wait_state(client, lambda s: s["report_phase"] == "ready")
    prefix = "/api/report/" + state["report_version"]
    assert get(client, prefix + "/data").json == {"synthetic": True}
    view = get(client, prefix + "/view")
    assert b"ASSET_BASE" not in view.data
    assert "script-src" not in view.headers["Content-Security-Policy"]
    assert get(other, prefix + "/view").status_code == 409
    asset = prefix + "/assets/" + "a" * 24 + ".png"
    assert get(client, asset).data == b"synthetic-png"
    assert get(other, asset).status_code == 409
    post(client, "/api/clear", headers, {})
    assert get(client, prefix + "/view").status_code == 409
    assert get(client, asset).status_code == 409
    assert get(client, "/api/export").status_code == 409
    assert not app.extensions["local_store"].budget.sizes


def test_clearing_inflight_report_cannot_restore_data(app, capture):
    client, headers = visitor(app)
    builder = app.extensions["local_store"].builder
    builder.release.clear()
    import_capture(client, headers, capture)
    post(client, "/api/report", headers, {"friend": False, "support": False})
    assert builder.entered.wait(1)
    assert get(client, "/api/state").json["report_progress"] == {
        "stage": "images",
        "completed": 1,
        "total": 3,
    }
    post(client, "/api/clear", headers, {})
    builder.release.set()
    state = get(client, "/api/state").json
    assert state["phase"] == "cleared" and state["report_phase"] == "idle"
    assert not state["report_version"] and not state["download_ready"]
    assert state["report_progress"] == {}


def test_statistics_expiry_also_clears_report_and_assets(app, capture):
    client, headers = visitor(app)
    import_capture(client, headers, capture)
    post(client, "/api/report", headers, {"friend": False, "support": False})
    state = wait_state(client, lambda s: s["report_phase"] == "ready")
    session = app.extensions["local_store"].get(
        client.get_cookie("fgo-visitor", domain="127.0.0.1").value
    )
    session.expires = 0
    assert get(client, "/api/report/" + state["report_version"] + "/view").status_code == 409
    assert get(client, "/api/state").json["preview"] is None


def test_import_body_size_and_options_are_bounded(app):
    client, headers = visitor(app)
    assert (
        post(client, "/api/report", headers, {"friend": "true", "support": False}).status_code
        == 409
    )
    response = client.post(
        "/api/import",
        base_url="http://127.0.0.1:55313",
        data=b"x" * (16 * 1024 * 1024 + 1),
        content_type="application/octet-stream",
        headers={**headers, "X-FGO-Consent": "yes", "X-FGO-Server": "ios"},
    )
    assert response.status_code == 413 and response.json["error"] == "INPUT_TOO_LARGE"


def test_capacity_is_recovered_when_visitor_expires():
    app = create_app(LocalConfig(max_sessions=1), cleanup=False)
    try:
        client, _ = visitor(app)
        other = app.test_client()
        assert get(other, "/").status_code == 429
        session = app.extensions["local_store"].get(
            client.get_cookie("fgo-visitor", domain="127.0.0.1").value
        )
        session.deadline = 0
        assert get(client, "/api/state").status_code == 401
        assert get(other, "/").status_code == 200
    finally:
        app.extensions["local_store"].close()


def test_qr_uses_selected_game_server_and_drops_auth(monkeypatch, capture):
    expected, preview = export_statistics(capture)
    selected = []

    class Client:
        def __init__(self, profile, server):
            selected.append(server)

        def generate(self):
            return "synthetic-ticket", "https://example.invalid/synthetic-qr"

        def poll(self, ticket):
            return "authorized", {"access_token": "synthetic-secret"}

        def statistics(self, user, progress, cancelled):
            progress("fetching_statistics")
            return expected, preview.copy()

    monkeypatch.setattr("fgo_local_exporter.login_session.GameClient", Client)
    profile = GameProfile("2.129.0", {}, "synthetic", "synthetic", "synthetic")
    app = create_app(profile=profile, cleanup=False)
    try:
        client, headers = visitor(app)
        assert (
            post(client, "/api/start", headers, {"server": "ios", "consent": True}).status_code
            == 200
        )
        state = wait_state(client, lambda s: s["phase"] == "complete")
        assert state["server"] == "ios" and selected == ["ios"]
        assert b"synthetic-secret" not in get(client, "/api/state").data
        session = app.extensions["local_store"].get(
            client.get_cookie("fgo-visitor", domain="127.0.0.1").value
        )
        assert not session.auth
        assert get(client, "/api/export").data == expected
    finally:
        app.extensions["local_store"].close()
