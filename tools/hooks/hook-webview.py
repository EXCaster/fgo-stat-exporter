"""只收集 Windows 窗口后端实际引用的组件与加载目录。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

_, package = get_package_paths("webview")
datas = collect_data_files("webview", subdir="js")
binaries = []
for name in (
    "lib/Microsoft.Web.WebView2.Core.dll",
    "lib/Microsoft.Web.WebView2.WinForms.dll",
    "lib/WebBrowserInterop.x64.dll",
    "lib/runtimes/win-x64/native/WebView2Loader.dll",
    "lib/runtimes/win-x86/native/WebView2Loader.dll",
    "lib/runtimes/win-arm64/native/WebView2Loader.dll",
):
    source = Path(package) / name
    if not source.is_file():
        raise RuntimeError("缺少桌面窗口运行组件")
    binaries.append((str(source), "webview/" + str(Path(name).parent)))
