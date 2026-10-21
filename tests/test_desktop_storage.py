"""数据目录选择使用临时目录，不读写实际用户的设置。"""

from pathlib import Path

import pytest

from fgo_local_exporter.desktop_storage import (
    browser_session_directory,
    read_startup_directory,
    validate_data_directory,
)
from fgo_local_exporter.errors import ExportError


class MemorySettings:
    def __init__(self, directory=None):
        self.directory = directory
        self.saved = []

    def read(self):
        return self.directory

    def save(self, directory):
        self.saved.append(directory)
        self.directory = directory


def test_first_start_has_no_directory_and_does_not_create_appdata(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    settings = MemorySettings()
    assert read_startup_directory(settings=settings) is None
    assert settings.saved == []
    assert not appdata.exists()
    assert list(tmp_path.iterdir()) == []


def test_second_start_reuses_selection_without_prompting(tmp_path):
    selected = tmp_path / "data"
    settings = MemorySettings(selected)

    assert read_startup_directory(settings=settings) == selected
    assert settings.saved == []


def test_unavailable_saved_directory_returns_to_page_and_retains_existing_file(tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("existing file")
    settings = MemorySettings(occupied)
    assert read_startup_directory(settings=settings) is None
    assert settings.saved == []
    assert occupied.read_text() == "existing file"


def test_explicit_directory_does_not_overwrite_remembered_selection(tmp_path):
    settings = MemorySettings(tmp_path / "remembered")
    selected = tmp_path / "override"
    assert read_startup_directory(selected, settings=settings) == selected
    assert settings.directory == tmp_path / "remembered" and settings.saved == []


@pytest.mark.parametrize("directory", ["relative", r"\\server\share\data"])
def test_data_directory_rejects_relative_and_network_paths(directory):
    with pytest.raises(ExportError, match="DATA_DIRECTORY_UNAVAILABLE"):
        validate_data_directory(directory)


def test_data_directory_rejects_drive_root(tmp_path):
    with pytest.raises(ExportError, match="DATA_DIRECTORY_UNAVAILABLE"):
        validate_data_directory(Path(tmp_path.anchor))


def test_write_failure_leaves_user_files_untouched(tmp_path, monkeypatch):
    original = tmp_path / "keep.txt"
    original.write_text("keep")

    def denied(**_kwargs):
        raise PermissionError("synthetic write failure")

    monkeypatch.setattr("fgo_local_exporter.desktop_storage.tempfile.TemporaryFile", denied)
    with pytest.raises(ExportError, match="DATA_DIRECTORY_UNAVAILABLE"):
        validate_data_directory(tmp_path)
    assert original.read_text() == "keep"
    assert list(tmp_path.iterdir()) == [original]


def test_browser_uses_unique_directories_and_preserves_existing_files(tmp_path):
    browser = tmp_path / "webview"
    browser.mkdir()
    existing = browser / "keep.txt"
    existing.write_text("existing file")
    with (
        browser_session_directory(tmp_path) as first,
        browser_session_directory(tmp_path) as second,
    ):
        assert first.parent == second.parent == browser
        assert first != second and first.is_dir() and second.is_dir()
    assert not first.exists() and not second.exists()
    assert existing.read_text() == "existing file"


def test_unconfigured_browser_is_temporary_and_cleans_up_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("fgo_local_exporter.desktop_storage.tempfile.tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with browser_session_directory() as path:
            assert path.parent == tmp_path and path.is_dir()
            (path / "runtime-cache").write_bytes(b"synthetic")
            raise RuntimeError("synthetic failure")
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["resources", "webview"])
def test_data_directory_rejects_occupied_subdirectory_names(tmp_path, name):
    occupied = tmp_path / name
    occupied.write_text("existing file")
    with pytest.raises(ExportError, match="DATA_DIRECTORY_UNAVAILABLE"):
        validate_data_directory(tmp_path)
    assert occupied.read_text() == "existing file"


@pytest.mark.parametrize("name", ["resources", "webview"])
def test_data_directory_rejects_junction_subdirectories(tmp_path, monkeypatch, name):
    monkeypatch.setattr(Path, "is_junction", lambda path: path == tmp_path / name)
    with pytest.raises(ExportError, match="DATA_DIRECTORY_UNAVAILABLE"):
        validate_data_directory(tmp_path)
