"""桌面数据目录选择与路径设置。"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.local_files import local_directory_path

__all__ = [
    "StorageSettings",
    "read_startup_directory",
    "browser_session_directory",
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


@contextmanager
def browser_session_directory(directory=None):
    """只清理本次浏览器目录；未选数据目录时使用退出即清除的临时目录。"""
    root = None
    if directory is not None:
        root = validate_data_directory(directory) / "webview"
        root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fgo-stat-webview-", dir=root) as name:
        yield Path(name)


def read_startup_directory(explicit=None, *, settings=None):
    """只读取已选目录。没有可用目录时先进入页面，不弹出选择器。"""
    if explicit is not None:
        return validate_data_directory(explicit)
    settings = settings or StorageSettings()
    previous = settings.read()
    if previous is not None:
        try:
            return validate_data_directory(previous)
        except ExportError:
            pass
    return None
