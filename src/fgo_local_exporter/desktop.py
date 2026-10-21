"""Windows 独立窗口，网络业务及报告处理全部由本机进程完成。"""

import argparse
import logging
import os
import socket
import sys
import threading
from pathlib import Path

from flask import Response
from werkzeug.serving import WSGIRequestHandler, make_server

from fgo_local_exporter import __version__
from fgo_local_exporter.desktop_bridge import DesktopBridge
from fgo_local_exporter.desktop_reports import engine_source
from fgo_local_exporter.desktop_resources import ResourceManager
from fgo_local_exporter.desktop_storage import (
    StorageSettings,
    browser_session_directory,
    read_startup_directory,
)
from fgo_local_exporter.local_api import create_app
from fgo_local_exporter.settings import LocalConfig

__all__ = ["create_desktop_app", "main"]

_STATIC = Path(__file__).with_name("desktop_static")


class _SilentHandler(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def create_desktop_app(config, bridge):
    app = create_app(config)
    bridge._store = app.extensions["local_store"]

    @app.get("/desktop.js")
    def javascript():
        return Response((_STATIC / "desktop.js").read_bytes(), content_type="text/javascript")

    @app.get("/desktop.css")
    def stylesheet():
        return Response((_STATIC / "desktop.css").read_bytes(), content_type="text/css")

    return app


def main():
    import webview

    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--data-dir", type=Path, help="指定字典、图片缓存和浏览器数据目录")
    parser.add_argument(
        "--protocol", type=Path, help="指定固定协议配置，默认读取 game-protocol.json"
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    storage = StorageSettings()
    data_root = read_startup_directory(args.data_dir, settings=storage)
    source = engine_source()
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(source))
    resources = ResourceManager(data_root / "resources") if data_root is not None else None
    server = None
    for _ in range(5):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = LocalConfig(
            origin=f"http://127.0.0.1:{port}",
            engine_source=source,
            max_sessions=4,
            memory_bytes=192 * 1024 * 1024,
        )
        bridge = DesktopBridge(
            config, resources, profile_path=args.protocol, data_root=data_root, storage=storage
        )
        app = create_desktop_app(config, bridge)
        try:
            server = make_server(
                "127.0.0.1", port, app, threaded=True, request_handler=_SilentHandler
            )
            break
        except OSError:
            bridge._store.close()
    if server is None:
        raise RuntimeError("LOCAL_PORT_UNAVAILABLE")
    bundled = args.resources or (
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "report-resources"
    )
    if bundled.is_dir():
        bridge._asset_root = bundled
    if resources is not None:
        bridge._initialize_resources()
    bridge._restore_profile()
    window = webview.create_window(
        f"FGO 抓包统计 {__version__}",
        config.origin,
        js_api=bridge,
        width=1280,
        height=900,
        min_size=(1000, 720),
    )
    bridge._window = window
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with browser_session_directory(data_root) as browser_directory:
            webview.start(
                gui="edgechromium",
                private_mode=True,
                debug=False,
                storage_path=str(browser_directory),
            )
    finally:
        if bridge._resources is not None:
            bridge._resources.stop.set()
        bridge._store.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
