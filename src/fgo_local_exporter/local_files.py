"""显式保存时只接受本机固定磁盘，不跟随网络路径。"""

import os

from fgo_local_exporter.errors import ExportError


def local_directory_path(path):
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ExportError("EXPORT_DIRECTORY_UNAVAILABLE")
    resolved = path.resolve()
    if str(resolved).startswith(("\\\\", "//")):
        raise ExportError("EXPORT_DIRECTORY_UNAVAILABLE")
    if os.name == "nt":
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        if drive_type(resolved.anchor) != 3:
            raise ExportError("EXPORT_DIRECTORY_UNAVAILABLE")
    return resolved
