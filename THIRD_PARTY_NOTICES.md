# 第三方依赖与资源

本项目代码采用 MIT，见 `LICENSE`。安装包只包含运行所需编译模块和资源；第三方代码与许可证保留原版权文字。

运行依赖包括 Python、pywebview、pythonnet、clr-loader、cffi、Flask、Werkzeug、Jinja2、qrcode、PyCryptodome、Pydantic、Pillow、httpx 及其依赖。客户端界面使用 html-to-image 1.11.13（MIT），许可见 `licenses/html-to-image-MIT.txt`。PyInstaller 引导程序遵循其许可证与引导程序例外。实际构建会从已安装发行版逐项收集许可并记录版本。

安卓版使用 Chaquopy（MIT）、AndroidX WebKit（Apache-2.0）、OpenSSL（Apache-2.0）、FreeType（FreeType License）、libjpeg-turbo（BSD 及 IJG）及 Python。相关许可保留在 APK 的许可证资源及依赖元数据中；构建工具不属于客户端运行载荷。

系统 WebView2 Runtime 由微软提供；程序不附带完整浏览器。公开字典和图片来自 Chaldea 与 Atlas Academy，保留各自数据及素材权利。字体按原许可使用。原生助战资源不受本项目 MIT 许可证覆盖，源码仓库不附带游戏纹理与字库。

资源清单中的路径、哈希与版本仅用于一致性校验，不表示对第三方素材拥有版权或额外授权。

应用图标使用 FGO 街机启动器图标，相关游戏图像权利归原权利人所有，不适用本项目的 MIT 许可。
