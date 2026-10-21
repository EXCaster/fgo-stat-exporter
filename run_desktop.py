"""Windows 桌面客户端入口；子进程只经匿名管道接收待过滤文件。"""

import sys

if __name__ == "__main__":
    if "--import-worker" in sys.argv:
        # 无控制台程序通过匿名管道工作时，显式恢复标准输入和输出。
        if getattr(sys, "frozen", False):
            import ctypes
            import io
            import msvcrt
            import os

            get_handle = ctypes.windll.kernel32.GetStdHandle
            get_handle.argtypes = [ctypes.c_ulong]
            get_handle.restype = ctypes.c_void_p
            for name, handle_id, flags, mode in (
                ("stdin", -10, os.O_RDONLY | os.O_BINARY, "rb"),
                ("stdout", -11, os.O_WRONLY | os.O_BINARY, "wb"),
            ):
                descriptor = msvcrt.open_osfhandle(get_handle(handle_id), flags)
                setattr(sys, name, io.TextIOWrapper(os.fdopen(descriptor, mode), encoding="utf-8"))
        from fgo_local_exporter.import_worker import main
    else:
        from fgo_local_exporter.desktop import main
    main()
