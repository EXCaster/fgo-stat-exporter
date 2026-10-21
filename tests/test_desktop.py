import json
import os
import re
import time

import pytest
from test_desktop_storage import MemorySettings

from fgo_local_exporter.desktop import create_desktop_app
from fgo_local_exporter.desktop_bridge import DesktopBridge
from fgo_local_exporter.desktop_profile import load_cached_profile, save_cached_profile
from fgo_local_exporter.desktop_resources import ResourceManager
from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.settings import LocalConfig


def profile():
    # 仅为格式校验构造参数，不来自游戏或账号。
    return GameProfile(
        "2.129.0",
        {
            "merchant_id": "1",
            "game_id": "112",
            "app_id": "112",
            "server_id": "248",
            "version": "3",
            "sdk_type": "1",
        },
        "SyntheticSDKKey1234567890",
        "SyntheticDevelopment123456",
        "SyntheticSessionPrefix123456",
    )


@pytest.mark.skipif(os.name != "nt", reason="DPAPI 需要 Windows 当前用户")
def test_protocol_cache_is_encrypted_and_excludes_account_fields(tmp_path):
    path = tmp_path / "protocol.dpapi"
    original = profile()
    save_cached_profile(path, original)
    raw = path.read_bytes()
    assert original.sdk_key.encode() not in raw
    assert original.development_code.encode() not in raw
    assert original.session_prefix.encode() not in raw
    restored = load_cached_profile(path)
    assert restored.sdk_key == original.sdk_key
    assert restored.session_prefix == original.session_prefix
    assert set(restored.__dict__) == {
        "version",
        "sdk_base",
        "sdk_key",
        "development_code",
        "session_prefix",
    }


@pytest.mark.skipif(os.name != "nt", reason="DPAPI 需要 Windows 当前用户")
def test_corrupted_protocol_cache_fails_without_echoing_data(tmp_path):
    path = tmp_path / "protocol.dpapi"
    path.write_bytes(b"FGOP1\0not-an-encrypted-game-profile")
    with pytest.raises(ExportError) as error:
        load_cached_profile(path)
    assert error.value.code == "LOCAL_PROFILE_ENCRYPTION_FAILED"
    assert "not-an-encrypted" not in str(error.value)


def make_app(tmp_path):
    resources = ResourceManager(tmp_path / "resources")
    config = LocalConfig(origin="http://127.0.0.1:55313")
    bridge = DesktopBridge(config, resources)
    bridge._profile_path = tmp_path / "game-protocol.json"
    app = create_desktop_app(config, bridge)
    app.config["SERVER_NAME"] = config.host
    client = app.test_client()
    page = client.get("/").get_data(as_text=True)
    csrf = re.search(r'name="fgo-csrf" content="([^"]+)"', page)[1]
    return app, client, bridge, page, csrf


def test_desktop_page_uses_local_privacy_text_without_automatic_emulator_read(tmp_path):
    app, client, bridge, page, csrf = make_app(tmp_path)
    try:
        assert "数据仅在本机临时处理" in page
        assert "desktop-login-state" not in page
        assert "字典保存位置" in page
        assert "加载统计JSON（可导入chaldea）" in page
        assert "首次读取原版 APK" not in page
        assert "从模拟器读取" not in page
        assert 'id="desktop-progress"' in page
        assert client.get("/desktop.css").status_code == 200
        assert "服务器内存中的统计数据" not in page
        script = client.get("/desktop.js").get_data(as_text=True)
        assert 'if (initial.game_phase === "idle")' not in script
        assert bridge.connect(csrf)["ok"]
        assert not bridge.connect("invalid-token")["ok"]
    finally:
        app.extensions["local_store"].close()


def test_window_bridge_does_not_expose_internal_objects_or_keys(tmp_path):
    app, client, bridge, page, csrf = make_app(tmp_path)
    try:
        bridge._store.profile = profile()
        assert all(name.startswith("_") for name in vars(bridge))
        result = bridge.connect(csrf)
        body = json.dumps(result)
        for value in (profile().sdk_key, profile().development_code, profile().session_prefix):
            assert value not in body
        assert not bridge.save_image("data:image/jpeg;base64,AAAA", "report.jpg", "x")["ok"]
    finally:
        app.extensions["local_store"].close()


def test_json_saved_only_after_explicit_local_save_dialog(tmp_path):
    app, client, bridge, page, csrf = make_app(tmp_path)
    try:
        bridge.connect(csrf)
        session = bridge._session
        session.export = b'{"synthetic_statistics":true}'
        session.phase = "complete"
        session.server = "ios"
        session.expires = time.monotonic() + 600
        target = tmp_path / "export.json"

        class Window:
            def create_file_dialog(self, *args, **kwargs):
                return str(target)

        bridge._window = Window()
        assert bridge.save_json()["saved"]
        assert target.read_bytes() == session.export
        assert bridge.save_json()["error"] == "EXPORT_PATH_EXISTS"
        session.clear()
        assert bridge.save_json()["error"] == "STATISTICS_NOT_READY"
    finally:
        app.extensions["local_store"].close()


def test_dictionary_folder_is_visible_and_opened_without_accepting_a_path(tmp_path, monkeypatch):
    app, client, bridge, page, csrf = make_app(tmp_path)
    root = tmp_path / "public-resources"
    (root / "data").mkdir(parents=True)
    bridge._resources.current = root
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    try:
        bridge.connect(csrf)
        assert bridge.status()["dictionary_directory"] == str(root / "data")
        assert bridge.open_dictionary_folder()["ok"]
        assert opened == [str(root / "data")]
    finally:
        app.extensions["local_store"].close()


def test_changing_data_directory_waits_for_restart_and_preserves_current_files(tmp_path):
    app, client, bridge, page, csrf = make_app(tmp_path)
    original = tmp_path / "keep.txt"
    original.write_text("existing data")
    selected = tmp_path / "new-data"
    bridge._storage = MemorySettings()

    class Window:
        result = (str(selected),)

        def create_file_dialog(self, *_args, **_kwargs):
            return self.result

    bridge._window = Window()
    try:
        bridge.connect(csrf)
        result = bridge.choose_data_directory()
        assert result["ok"] and result["restart_required"]
        assert bridge._storage.saved == [selected]
        assert bridge.status()["data_directory"] == str(tmp_path)
        assert bridge.status()["pending_data_directory"] == str(selected)
        assert bridge._resources.root == tmp_path / "resources"
        assert original.read_text() == "existing data"
        bridge._window.result = None
        assert bridge.choose_data_directory() == {"ok": True, "changed": False}
        assert bridge.status()["pending_data_directory"] == str(selected)
        bridge._window.result = (str(tmp_path),)
        assert not bridge.choose_data_directory()["restart_required"]
        assert bridge.status()["pending_data_directory"] == ""
    finally:
        app.extensions["local_store"].close()


@pytest.mark.parametrize(
    "filename,url",
    [
        ("../escape.json", "https://api.atlasacademy.io/repo/CN/master/mstShop.json"),
        ("safe.json", "https://unapproved.invalid/api/export"),
        ("safe.json", "https://127.0.0.1/private.json"),
        ("safe.json", "https://api.atlasacademy.io/repo/CN/file.json?token=synthetic"),
    ],
)
def test_resource_recipe_rejects_paths_and_unapproved_destinations(tmp_path, filename, url):
    manager = ResourceManager(tmp_path)
    with pytest.raises(ExportError, match="RESOURCE_MANIFEST_INVALID"):
        manager._file(tmp_path, {"filename": filename, "url": url, "bytes": 2, "sha256": "0" * 64})
