"""数据目录选择使用临时目录，不读写实际用户的设置。"""

from pathlib import Path

import pytest

from fgo_local_exporter.desktop_storage import (
    choose_startup_directory,
    create_browser_directory,
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


def test_first_start_uses_selected_directory_without_creating_appdata(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    selected = tmp_path / "自选数据目录"
    settings = MemorySettings()
    prompts = []

    def choose(previous, message):
        prompts.append((previous, message))
        return selected

    assert choose_startup_directory(settings=settings, chooser=choose) == selected
    assert prompts == [(None, "")]
    assert settings.saved == [selected]
    assert selected.is_dir() and list(selected.iterdir()) == []
    assert not appdata.exists()


def test_second_start_reuses_selection_without_prompting(tmp_path):
    selected = tmp_path / "data"
    settings = MemorySettings(selected)

    def unexpected(*_args):
        pytest.fail("已选目录可用时不应再次弹窗")

    assert choose_startup_directory(settings=settings, chooser=unexpected) == selected
    assert settings.saved == []


def test_cancel_first_start_does_not_create_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    settings = MemorySettings()
    assert choose_startup_directory(settings=settings, chooser=lambda *_args: None) is None
    assert settings.saved == []
    assert list(tmp_path.iterdir()) == []


def test_unavailable_saved_directory_prompts_and_retains_existing_file(tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("existing file")
    selected = tmp_path / "replacement"
    prompts = []

    def choose(previous, message):
        prompts.append((previous, message))
        return selected

    assert choose_startup_directory(settings=MemorySettings(occupied), chooser=choose) == selected
    assert prompts[0][0] == occupied and "不可用" in prompts[0][1]
    assert occupied.read_text() == "existing file"


def test_invalid_choice_can_be_cancelled_without_replacing_setting(tmp_path):
    settings = MemorySettings()
    prompts = []

    def choose(previous, message):
        prompts.append((previous, message))
        return Path("relative") if len(prompts) == 1 else None

    assert choose_startup_directory(settings=settings, chooser=choose) is None
    assert "无法写入" in prompts[1][1]
    assert settings.saved == []


def test_explicit_directory_does_not_overwrite_remembered_selection(tmp_path):
    settings = MemorySettings(tmp_path / "remembered")
    selected = tmp_path / "override"
    assert choose_startup_directory(selected, settings=settings) == selected
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


def test_failed_settings_write_allows_cancel_without_falling_back_to_appdata(tmp_path):
    class FailedSettings(MemorySettings):
        def save(self, directory):
            raise ExportError("DATA_SETTINGS_UNAVAILABLE")

    prompts = []

    def choose(previous, message):
        prompts.append((previous, message))
        return tmp_path / "chosen" if len(prompts) == 1 else None

    assert choose_startup_directory(settings=FailedSettings(), chooser=choose) is None
    assert "无法记住" in prompts[1][1]


def test_browser_uses_unique_directories_and_preserves_existing_files(tmp_path):
    browser = tmp_path / "webview"
    browser.mkdir()
    existing = browser / "keep.txt"
    existing.write_text("existing file")
    first = create_browser_directory(tmp_path)
    second = create_browser_directory(tmp_path)
    assert first.parent == second.parent == browser
    assert first != second and first.is_dir() and second.is_dir()
    assert existing.read_text() == "existing file"


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
