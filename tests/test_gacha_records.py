"""人工卡池记录验证时间排序、分页、按需图片和访客隔离。"""

import copy
import json
import re
import threading
from types import SimpleNamespace

import pytest

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.local_api import create_app
from fgo_local_exporter.reports import ReportBuilder
from fgo_local_exporter.statistics import decode_response, export_statistics
from fgo_stat_core.contracts.models import CaptureError
from fgo_stat_core.contracts.report_master import GachaMaster, ReportMasterData
from fgo_stat_core.features.capture_import.parser import parse_capture
from fgo_stat_core.features.report.gacha_records import build_gacha_history, gacha_page

KEY = b"SYNTHETIC-GACHA-KEY-00000000000000"


@pytest.fixture
def master():
    return ReportMasterData(
        revision="synthetic-only",
        timestamp=1_700_000_000,
        gachas={
            101: GachaMaster(101, "人工常驻池", 1, 1_600_000_000, 2_140_000_000, 33),
            201: GachaMaster(201, "人工福袋", 7, 1_700_000_000, 1_710_000_000, 33),
            202: GachaMaster(202, "人工限时池", 1, 1_720_000_000, 1_721_000_000, 34),
            1: GachaMaster(1, "人工友情池", 3, 0, 0, 0),
        },
    )


@pytest.fixture
def capture(minimal_capture):
    minimal_capture["cache"]["replaced"].update(
        {
            "userGacha": [
                {"gachaId": 101, "num": 4, "token": "SYNTHETIC-ONLY-SECRET"},
                {"gachaId": 201, "num": 11},
                {"gachaId": 202, "num": 30},
                {"gachaId": 1, "num": 3},
                {"gachaId": 999999, "num": 300},
            ],
            "userSvt": [],
            "userSvtCollection": [],
        }
    )
    return minimal_capture


def history(capture, master):
    return build_gacha_history(
        parse_capture(json.dumps(capture).encode(), KEY, report_fields=True), master
    )


def test_default_pins_friend_and_permanent_then_orders_other_pools_by_time(capture, master):
    value = history(capture, master)
    assert [row.gacha_id for row in value.records] == [1, 101, 202, 201, 999999]
    assert [row["gacha_id"] for row in gacha_page(value)["rows"]] == [1, 101, 202, 201, 999999]
    assert gacha_page(value, sort="pulls")["rows"][0]["gacha_id"] == 999999
    assert gacha_page(value, sort="recent")["rows"][0]["gacha_id"] == 202
    assert gacha_page(value)["summary"]["pulls"] == 348


def test_complete_pool_list_keeps_more_than_top_100_and_reused_banners(capture, master):
    capture["cache"]["replaced"]["userGacha"].extend(
        {"gachaId": gid, "num": gid - 300} for gid in range(300, 881)
    )
    value = history(capture, master)
    assert len(value.records) == 586
    assert {row.gacha_id for row in value.records if row.image_id == 33} == {101, 201}
    first, last = gacha_page(value), gacha_page(value, page=20)
    assert first["total"] == 586 and first["pages"] == 20
    assert len(first["rows"]) == 30 and len(last["rows"]) == 16


def test_unknown_names_and_types_are_not_guessed_and_no_ssr_results_are_fabricated(capture, master):
    value = history(capture, master)
    unknown = gacha_page(value, kind="unknown")["rows"]
    assert len(unknown) == 1 and unknown[0]["name"] is None
    assert unknown[0]["opened_at"] is None and unknown[0]["image_id"] is None
    raw = value.model_dump_json()
    assert "SYNTHETIC-ONLY-SECRET" not in raw and '"ssr_count"' not in raw
    assert '"userId"' not in raw and '"servants"' not in raw
    assert repr(value) == "<GachaHistory>"


def test_search_matches_public_names_or_ids_and_handles_empty_results(capture, master):
    value = history(capture, master)
    assert gacha_page(value, query="福袋")["rows"][0]["pulls"] == 11
    assert gacha_page(value, query="202")["rows"][0]["gacha_id"] == 202
    assert gacha_page(value, query="没有这个卡池")["total"] == 0


@pytest.mark.parametrize(
    "kwargs", [{"page": 0}, {"page": True}, {"query": "a" * 101}, {"kind": "jp"}, {"sort": "url"}]
)
def test_invalid_queries_are_rejected(capture, master, kwargs):
    with pytest.raises(CaptureError, match="DETAILS_QUERY_INVALID"):
        gacha_page(history(capture, master), **kwargs)


def test_missing_table_is_different_from_an_empty_table(capture, master):
    capture["cache"]["replaced"]["userGacha"] = []
    assert gacha_page(history(capture, master))["available"] is True
    del capture["cache"]["replaced"]["userGacha"]
    assert gacha_page(history(capture, master))["available"] is False


class Builder:
    def __init__(self, master):
        self.master = master
        self.calls, self.image_calls = 0, 0
        self.version = "synthetic-gacha-v1"
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()

    def revision(self):
        return self.version

    def gacha_history(self, raw):
        self.calls += 1
        self.entered.set()
        self.release.wait(3)
        return history(json.loads(raw), self.master)

    def gacha_image(self, value, gacha_id):
        self.image_calls += 1
        assert gacha_id in {row.gacha_id for row in value.records}
        return b"SYNTHETIC-PUBLIC-IMAGE"


@pytest.fixture
def app(master):
    application = create_app(
        cleanup=False,
        builder=Builder(master),
        importer=lambda raw: export_statistics(decode_response(raw)),
    )
    yield application
    application.extensions["local_store"].builder.release.set()
    application.extensions["local_store"].close()


def visitor(app):
    client = app.test_client()
    response = client.get("/", base_url="http://127.0.0.1:55313")
    csrf = re.search(rb'name="fgo-csrf" content="([^"]+)"', response.data)[1].decode()
    return client, {"Origin": "http://127.0.0.1:55313", "X-FGO-CSRF": csrf}


def get(client, path):
    return client.get(path, base_url="http://127.0.0.1:55313")


def session(app, client):
    return app.extensions["local_store"].get(
        client.get_cookie("fgo-visitor", domain="127.0.0.1").value
    )


def import_data(app, client, capture):
    body, preview = export_statistics(capture)
    current = session(app, client)
    current.clear()
    current.cancel = threading.Event()
    current.server = "ios"
    current._complete_import(body, preview, current.generation, current.cancel)
    return current


def test_api_text_is_lazy_and_cache_is_private_to_visitor_and_generation(app, capture):
    client, headers = visitor(app)
    other, _ = visitor(app)
    current = import_data(app, client, capture)
    response = get(client, "/api/gachas")
    assert response.status_code == 200 and response.json["total"] == 5
    assert response.headers["Cache-Control"] == "no-store"
    builder = app.extensions["local_store"].builder
    assert builder.calls == 1 and builder.image_calls == 0
    assert get(client, "/api/gachas?kind=lucky").status_code == 200
    assert builder.calls == 1
    assert get(other, "/api/gachas").status_code == 409
    image = f"/api/gachas/101/image?generation={current.generation}"
    assert get(client, image).data == b"SYNTHETIC-PUBLIC-IMAGE"
    assert builder.image_calls == 1
    assert get(other, image).status_code == 409
    assert app.extensions["local_store"].budget.sizes[current.identifier] == current.memory_size()
    client.post("/api/clear", base_url="http://127.0.0.1:55313", headers=headers, json={})
    assert current.details is None and current.details_bytes == 0
    assert get(client, image).status_code == 409
    import_data(app, client, capture)
    assert get(client, image).status_code == 409 and builder.image_calls == 1


def test_cached_history_refreshes_after_resource_change_and_expires_with_statistics(app, capture):
    client, _ = visitor(app)
    current = import_data(app, client, capture)
    builder = app.extensions["local_store"].builder
    assert get(client, "/api/gachas").status_code == 200
    builder.version = "synthetic-gacha-v2"
    assert get(client, "/api/gachas").status_code == 200
    assert builder.calls == 2 and current.details_revision == builder.version
    current.expires = 0
    assert get(client, "/api/gachas").status_code == 409
    assert current.details is None and not app.extensions["local_store"].budget.sizes


@pytest.mark.parametrize(
    "query", ["?page=-1", "?page=1&page=2", "?q=x&q=y", "?url=https://example.invalid", "?kind=jp"]
)
def test_api_rejects_unbounded_or_unknown_query_parameters(app, capture, query):
    client, _ = visitor(app)
    import_data(app, client, capture)
    response = get(client, "/api/gachas" + query)
    assert response.status_code == 409 and response.json["error"] == "DETAILS_QUERY_INVALID"


def test_clear_during_calculation_cannot_restore_history(app, capture):
    client, _ = visitor(app)
    current = import_data(app, client, capture)
    builder = app.extensions["local_store"].builder
    builder.release.clear()
    result = []
    worker = threading.Thread(target=lambda: result.append(get(client, "/api/gachas")))
    worker.start()
    assert builder.entered.wait(1)
    current.clear()
    builder.release.set()
    worker.join(3)
    assert result[0].status_code == 409 and current.details is None and not current.export


def test_image_lookup_rejects_absent_pool_without_network(capture, master, tmp_path):
    builder = ReportBuilder.__new__(ReportBuilder)
    builder.config = SimpleNamespace(asset_dir=tmp_path)
    value = history(capture, master)
    for gid in (555555, 999999):
        with pytest.raises(ExportError, match="DETAILS_IMAGE_UNAVAILABLE"):
            builder.gacha_image(value, gid)
    assert not list(tmp_path.iterdir())


def test_input_limit_does_not_silently_drop_pools(capture, master):
    root = copy.deepcopy(capture)
    root["cache"]["replaced"]["userGacha"] = [{"gachaId": gid, "num": 1} for gid in range(1, 10002)]
    with pytest.raises(CaptureError, match="DETAILS_LIMIT"):
        history(root, master)
