"""桌面数据目录选择与路径设置。"""

import os
import tempfile
from pathlib import Path

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.local_files import local_directory_path

__all__ = [
    "StorageSettings",
    "choose_startup_directory",
    "create_browser_directory",
    "validate_data_directory",
]

_SETTINGS_KEY = r"Software\FGOStatExporter"


class StorageSettings:
    def read(self):
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY) as key:
                value, kind = winreg.QueryValueEx(key, "DataDirectory")
            if kind == winreg.REG_SZ and isinstance(value, str) and 0 < len(value) <= 4096:
                return Path(value)
        except OSError:
            pass
        return None

    def save(self, directory):
        import winreg

        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY) as key:
                winreg.SetValueEx(key, "DataDirectory", 0, winreg.REG_SZ, str(directory))
        except OSError:
            raise ExportError("DATA_SETTINGS_UNAVAILABLE") from None


def validate_data_directory(directory):
    """检查固定磁盘上的目录，只用临时探测文件确认写入权限。"""
    try:
        path = Path(directory)
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise ExportError("DATA_DIRECTORY_UNAVAILABLE")
        path = local_directory_path(path)
        if path == Path(path.anchor):
            raise ExportError("DATA_DIRECTORY_UNAVAILABLE")
        for child in (path / "resources", path / "webview"):
            if child.is_symlink() or child.is_junction() or (child.exists() and not child.is_dir()):
                raise ExportError("DATA_DIRECTORY_UNAVAILABLE")
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(prefix=".fgo-stat-write-", dir=path) as probe:
            probe.write(b"FGOStat")
            probe.flush()
            os.fsync(probe.fileno())
        return path
    except (OSError, ValueError, TypeError):
        raise ExportError("DATA_DIRECTORY_UNAVAILABLE") from None
    except ExportError:
        raise ExportError("DATA_DIRECTORY_UNAVAILABLE") from None


def create_browser_directory(directory):
    """浏览器退出时只清理本次创建的目录，不清理同名目录中的已有文件。"""
    root = validate_data_directory(directory) / "webview"
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="session-", dir=root))


def _folder_dialog(initial, message):
    # 启动 WebView 前先选目录，避免浏览器先在默认用户目录创建缓存。
    from webview.platforms.winforms import (
        ApartmentState,
        OpenFolderDialog,
        Thread,
        ThreadStart,
        WinForms,
    )

    result = {"directory": None, "failed": False}

    def show():
        try:
            if message:
                WinForms.MessageBox.Show(message, "FGO 抓包统计")
            paths = OpenFolderDialog.show(
                initialDirectory=str(initial) if initial is not None else None,
                title="选择数据目录（字典、图片缓存和浏览器数据）",
            )
            if paths:
                result["directory"] = Path(paths[0])
        except Exception:
            result["failed"] = True

    thread = Thread(ThreadStart(show))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    while thread.IsAlive:
        thread.Join(100)
    if result["failed"]:
        raise ExportError("DATA_DIRECTORY_UNAVAILABLE")
    return result["directory"]


def choose_startup_directory(explicit=None, *, settings=None, chooser=None):
    """沿用已选目录；首次启动或原目录不可用时重新选择。取消则退出。"""
    if explicit is not None:
        return validate_data_directory(explicit)
    settings = settings or StorageSettings()
    chooser = chooser or _folder_dialog
    previous = settings.read()
    message = ""
    if previous is not None:
        try:
            return validate_data_directory(previous)
        except ExportError:
            message = "原数据目录不可用，请选择其他目录。"
    while True:
        selected = chooser(previous, message)
        if selected is None:
            return None
        try:
            directory = validate_data_directory(selected)
            settings.save(directory)
            return directory
        except ExportError as error:
            message = (
                "无法记住数据目录，请检查 Windows 用户权限后重试。"
                if error.code == "DATA_SETTINGS_UNAVAILABLE"
                else "所选目录无法写入，请选择固定磁盘上的其他文件夹。"
            )
            previous = Path(selected)
