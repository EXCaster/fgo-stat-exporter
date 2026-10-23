"""使用人工二维码和延迟授权验证区服切换，不访问游戏接口。"""

import threading
import time

import pytest
from test_local_api import get, post, visitor, wait_state

from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.local_api import create_app
from fgo_local_exporter.login_session import LoginSession


@pytest.fixture
def qr_app(monkeypatch):
    monkeypatch.setattr(
        LoginSession, "_run", lambda self, generation, cancel, server: cancel.wait(5)
    )
    profile = GameProfile("2.129.0", {}, "synthetic", "synthetic", "synthetic")
    app = create_app(profile=profile, cleanup=False)
    yield app
    app.extensions["local_store"].close()


def session_for(app, client):
    identifier = client.get_cookie("fgo-visitor", domain="127.0.0.1").value
    return app.extensions["local_store"].get(identifier)


@pytest.mark.parametrize("phase", ["generating", "waiting_scan", "waiting_confirm"])
@pytest.mark.parametrize("first,second", [("ios", "android"), ("android", "ios")])
def test_switch_cancels_old_qr_until_manual_generation(qr_app, phase, first, second):
    client, headers = visitor(qr_app)
    assert (
        post(client, "/api/start", headers, {"server": first, "consent": True}).status_code == 200
    )
    session = session_for(qr_app, client)
    with session.lock:
        session.phase = phase
        session.svg = b'<svg xmlns="http://www.w3.org/2000/svg">synthetic</svg>'
        generation, cancel = session.generation, session.cancel
    assert get(client, f"/api/qr.svg?generation={generation}").status_code == 200
    response = post(client, "/api/server", headers, {"server": second, "generation": generation})
    assert response.status_code == 200
    assert response.json["phase"] == "cleared" and response.json["server"] == second
    assert not response.json["has_qr"] and not response.json["can_switch_server"]
    assert cancel.is_set() and session.generation > generation and not session.auth
    assert get(client, f"/api/qr.svg?generation={generation}").status_code == 404
    response = post(client, "/api/start", headers, {"server": second, "consent": True})
    assert response.status_code == 200
    assert response.json["phase"] == "generating" and response.json["server"] == second
    assert response.json["can_switch_server"]
    session.svg = b'<svg xmlns="http://www.w3.org/2000/svg">new-synthetic</svg>'
    assert get(client, f"/api/qr.svg?generation={generation}").status_code == 404
    assert get(client, f"/api/qr.svg?generation={session.generation}").status_code == 200


@pytest.mark.parametrize(
    "phase", ["game_handoff", "game_initialization", "fetching_statistics", "filtering_statistics"]
)
def test_switch_is_rejected_after_game_login_starts(qr_app, phase):
    client, headers = visitor(qr_app)
    post(client, "/api/start", headers, {"server": "ios", "consent": True})
    session = session_for(qr_app, client)
    session.phase = phase
    generation = session.generation
    assert not get(client, "/api/state").json["can_switch_server"]
    response = post(client, "/api/server", headers, {"server": "android", "generation": generation})
    assert response.status_code == 409 and response.json["error"] == "OPERATION_NOT_READY"
    assert session.generation == generation and session.server == "ios"
    assert not session.cancel.is_set()


def test_switch_requires_current_generation_and_same_visitor(qr_app):
    client, headers = visitor(qr_app)
    post(client, "/api/start", headers, {"server": "ios", "consent": True})
    session = session_for(qr_app, client)
    generation = session.generation
    other, other_headers = visitor(qr_app)
    value = {"server": "android", "generation": generation}
    assert post(other, "/api/server", other_headers, value).status_code == 409
    assert post(client, "/api/server", {}, value).status_code == 403
    for invalid in [True, -1, "1", 1.0]:
        response = post(client, "/api/server", headers, {**value, "generation": invalid})
        assert response.status_code == 409 and response.json["error"] == "REQUEST_INVALID"
    response = post(client, "/api/server", headers, {**value, "generation": generation - 1})
    assert response.status_code == 409 and session.server == "ios"
    assert post(client, "/api/server", headers, value).status_code == 200
    assert post(client, "/api/server", headers, value).status_code == 409


def test_same_server_and_completed_statistics_are_preserved(qr_app):
    client, headers = visitor(qr_app)
    post(client, "/api/start", headers, {"server": "ios", "consent": True})
    session = session_for(qr_app, client)
    generation = session.generation
    same = post(client, "/api/server", headers, {"server": "ios", "generation": generation})
    assert same.status_code == 200 and session.generation == generation
    assert not session.cancel.is_set()
    with session.lock:
        session.phase, session.source = "complete", "file"
        session.export, session.expires = b"synthetic-statistics", time.monotonic() + 600
    response = post(client, "/api/server", headers, {"server": "android", "generation": generation})
    assert response.status_code == 409
    assert session.export == b"synthetic-statistics" and session.server == "ios"


def test_cancellation_does_not_require_another_qr_slot(qr_app):
    client, headers = visitor(qr_app)
    post(client, "/api/start", headers, {"server": "ios", "consent": True})
    session = session_for(qr_app, client)
    slots = qr_app.extensions["local_store"].qr_slots
    held = 0
    try:
        while slots.acquire(blocking=False):
            held += 1
        response = post(
            client,
            "/api/server",
            headers,
            {"server": "android", "generation": session.generation},
        )
        assert response.status_code == 200 and response.json["phase"] == "cleared"
    finally:
        for _ in range(held):
            slots.release()


def test_late_authorization_cannot_fetch_or_restore_old_server(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls, credentials = [], {"access_token": "synthetic-only"}

    class Client:
        def __init__(self, profile, server):
            self.server = server

        def generate(self):
            return "synthetic-ticket", "https://example.invalid/synthetic-qr"

        def poll(self, ticket):
            if self.server == "ios":
                entered.set()
                assert release.wait(3)
                return "authorized", credentials
            return "waiting_scan", {}

        def statistics(self, user, progress, cancelled):
            calls.append(self.server)
            raise AssertionError("已取消的授权不得进入取数")

    original = LoginSession._run

    def track(self, generation, cancel, server):
        try:
            original(self, generation, cancel, server)
        finally:
            if server == "ios":
                finished.set()

    monkeypatch.setattr("fgo_local_exporter.login_session.GameClient", Client)
    monkeypatch.setattr(LoginSession, "_run", track)
    profile = GameProfile("2.129.0", {}, "synthetic", "synthetic", "synthetic")
    app = create_app(profile=profile, cleanup=False)
    try:
        client, headers = visitor(app)
        post(client, "/api/start", headers, {"server": "ios", "consent": True})
        assert entered.wait(3)
        generation = get(client, "/api/state").json["generation"]
        assert (
            post(
                client,
                "/api/server",
                headers,
                {
                    "server": "android",
                    "generation": generation,
                },
            ).status_code
            == 200
        )
        post(client, "/api/start", headers, {"server": "android", "consent": True})
        wait_state(client, lambda state: state["phase"] == "waiting_scan")
        release.set()
        assert finished.wait(3)
        state = get(client, "/api/state").json
        assert state["server"] == "android" and state["has_qr"]
        assert not state["download_ready"] and not calls and not credentials
        assert not session_for(app, client).auth
    finally:
        release.set()
        app.extensions["local_store"].close()


def test_authorization_locks_server_before_statistics_callback(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Client:
        def __init__(self, profile, server):
            pass

        def generate(self):
            return "synthetic-ticket", "https://example.invalid/synthetic-qr"

        def poll(self, ticket):
            return "authorized", {"access_token": "synthetic-only"}

        def statistics(self, user, progress, cancelled):
            entered.set()
            release.wait(3)
            raise RuntimeError("人工结束取数")

    monkeypatch.setattr("fgo_local_exporter.login_session.GameClient", Client)
    profile = GameProfile("2.129.0", {}, "synthetic", "synthetic", "synthetic")
    app = create_app(profile=profile, cleanup=False)
    try:
        client, headers = visitor(app)
        post(client, "/api/start", headers, {"server": "ios", "consent": True})
        assert entered.wait(3)
        state = get(client, "/api/state").json
        assert state["phase"] == "game_handoff" and not state["can_switch_server"]
        response = post(
            client,
            "/api/server",
            headers,
            {
                "server": "android",
                "generation": state["generation"],
            },
        )
        assert response.status_code == 409 and session_for(app, client).server == "ios"
    finally:
        release.set()
        app.extensions["local_store"].close()
