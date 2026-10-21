# FGO 抓包统计

FGO 国服账号统计工具，支持 Windows 和 Android。可以扫码登录，也可以导入已有的统计 JSON 或国服登录响应，生成统计图、导出 JSON。

支持 iOS 和安卓区服。无需安装游戏、Root、代理或证书。登录请求直接发送到官方接口，字典和图片从 Chaldea、Atlas Academy 等公开数据源获取。

## 使用

- **Windows**：Windows 10 / 11 64 位，需要 Microsoft Edge WebView2 Runtime。运行 `FGOStatDesktop.exe`，进入页面后点击“选择数据目录”，设置字典和图片缓存的保存位置，之后可以在界面更换。扫码前请完成下方配置。
- **Android**：Android 7.0 及以上，支持 `arm64-v8a`、`x86_64`，不支持 32 位设备。需要支持 Web Message Listener 的 Android System WebView 或 Chrome。安装 APK 后运行。

1. 区服默认选择 iOS，安卓角色请切换到安卓区服。
2. 扫码登录，或选择“导入文件”。扫码时请核对官方客户端显示的授权应用为“命运-冠位指定”。
3. 核对角色信息，选择是否显示助战编成、好友 ID，再生成统计图或保存 JSON。好友 ID 默认隐藏。

页面右上角的“GitHub 仓库”可打开项目源码仓库，Windows 和 Android 均使用系统浏览器打开。

Windows 可选择图片和 JSON 的保存位置。Android 图片直接保存到相册的“FGO抓包统计”，JSON 通过系统文件保存器保存。Android 7–9 首次保存图片需要存储权限，Android 10 及以上不需要。长图保存失败时可尝试分段保存。

详细操作见 [Windows 使用说明](DESKTOP.md) 和 [Android 使用说明](ANDROID_USER.md)。

## 扫码登录配置

仓库不提供 SDK 密钥和会话算法参数。首次配置时，在项目根目录复制模板：

```powershell
Copy-Item game-protocol.example.json game-protocol.json
```

在 `game-protocol.json` 中填写 `sdk_key`、`development_code`、`session_prefix`，其余字段按模板设置。该文件已加入 `.gitignore`，请勿提交到仓库。

源码运行和 Android 构建默认读取项目根目录的这份配置。Windows EXE 读取同目录的 `game-protocol.json`；在项目目录内运行时会查找项目根目录，也可通过 `--protocol 文件路径` 指定。修改配置后重启程序。

Android 构建会将配置打入 APK。Windows EXE 不包含这些参数。没有配置也能编译、导入文件和生成图片，扫码取数需要配置。

## 资源与数据目录

设置数据目录后，启动时自动检查资源更新，也可点击“检查资源更新”手动检查。界面会显示字典版本、文件数量、图片缓存数量、保存位置和更新进度。

字典包含统计用到的从者、礼装、卡池、关卡、技能和名称等数据。每次检查都会读取上游版本清单，下载变化的文件；全部校验通过后才启用。下载失败、数据格式不兼容或下载期间上游再次更新时，继续使用原版本。

统计图片来自 Atlas Academy，生成报告时按需下载并缓存。更新字典后，点击“重新生成统计图”使用新数据和图片。更新进度取决于公开数据源的发布时间；登录协议、数据格式或程序界面的变更需要更新应用。

Windows 首次启动直接进入页面，点击“选择数据目录”后才准备资源，可以选择其他磁盘。取消选择会留在页面，之后可继续设置。首次选择立即生效；已有目录的用户点击“更换数据目录”后重启生效，原目录文件会保留。目录路径记在 Windows 用户设置中。EXE 的解包目录与首次打开页面所需的浏览器目录使用系统临时目录；浏览器临时目录退出时清除。

## 从源码运行

需要 Python 3.13、uv 和 WebView2 Runtime。在项目根目录执行：

```powershell
uv sync --extra desktop --group build --group dev
uv run python run_desktop.py
```

可用 `--data-dir` 指定数据目录，`--resources` 指定已有资源：

```powershell
uv run python run_desktop.py --data-dir D:\FGOStatData --resources D:\FGOResources
```

`--data-dir` 只对这次启动生效。已有资源目录应包含完整的 `data`、`atlas-cn`、`assets`；未指定时使用内置资源，源码环境缺少内置资源时从公开源下载。

## 编译

Windows：

```powershell
uv run python tools/build_desktop.py --output build\desktop
```

生成的程序位于 `build\desktop\candidate\FGOStatDesktop.exe`。EXE 内置基础字典、图片、使用说明和许可证，可在界面点击“使用说明与许可”查看。

构建时可通过 `--resources D:\FGOResources` 使用已有资源。原生助战布局另需 `native-ui` 资源，未提供时使用标准布局。

Android 构建需要 JDK 17、Android SDK 35、NDK 28.2 和 Chaquopy，步骤见 [ANDROID.md](ANDROID.md)。签名文件和口令请自行保管，不要提交到仓库。

## 代码结构

- `src/fgo_local_exporter/protocol.py`：扫码授权和游戏请求。
- `game_profile.py`：协议配置读取与校验。
- `login_session.py`、`sessions.py`：登录、导入和报告的会话管理。
- `statistics.py`、`import_worker.py`：文件解析和统计字段提取。
- `resource_catalog.py`、`desktop_resources.py`：资源版本查询、下载、校验和缓存。
- `reports.py`、`desktop_reports.py`：统计与报告生成。
- `desktop.py`、`desktop_bridge.py`、`desktop_storage.py`：Windows 窗口、文件操作和数据目录设置。
- `mobile.py`、`android/`：Android 运行时、文件选择器和相册保存。
- `local_api.py`、`ui/`、`desktop_static/`、`mobile_static/`：界面和应用内通信。
- `src/fgo_stat_core/`：数据模型、统计计算、报告模板和助战组件。
- `tools/`：构建、资源整理和安装包检查。
- `tests/`：测试。

## 测试

```powershell
uv run ruff check src tests tools run_desktop.py
uv run pytest -q
```

测试环境、结果和兼容范围见 [VALIDATION.md](VALIDATION.md)。

## 隐私与许可

登录凭据和原始响应只在内存中处理，不写入磁盘、数据库或日志。统计和报告最多保留 10 分钟，也可立即清除。导出的文件不含登录凭据，但可能包含角色名等个人信息，请妥善保管。主动保存的文件、相册图片和公开资源缓存会保留在设备上。

本工具与《Fate/Grand Order》、bilibili 及相关运营方无关联，不属于官方服务。项目代码采用 [MIT 许可证](LICENSE)；游戏素材、图标、字体、第三方数据和依赖的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
