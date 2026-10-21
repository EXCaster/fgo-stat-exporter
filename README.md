# FGO 抓包统计

在 Windows 或安卓设备上读取 FGO 国服账号统计，生成统计图并导出 JSON。支持 iOS、安卓区服，以及已有统计 JSON、国服登录响应文件的导入。

扫码授权、游戏请求、文件解析和图片生成均在当前设备完成。不需要 Root、安装游戏、设置代理或导入证书。网络请求用于官方登录、游戏接口和公开字典、图片源。

## 使用

- Windows：直接运行单个 EXE，需要 Windows 10 / 11 64 位及 Microsoft Edge WebView2 Runtime。内置基础字典、图片、说明和许可证，无需附带其他文件；可在界面点击“使用说明与许可”查看。操作说明见 [DESKTOP.md](DESKTOP.md)。
- 安卓：安装 APK 后运行，需要 Android 7.0 及以上、64 位 ARM 或 x86 设备，以及支持 Web Message Listener 的较新 WebView。操作说明见 [ANDROID_USER.md](ANDROID_USER.md)。当前 APK 不包含 32 位架构。

选择角色所在区服后，扫码或导入文件。扫码时用官方客户端核对授权应用为“命运-冠位指定”，自行确认授权。取得数据后先核对角色信息，再生成统计图或保存 JSON。

好友 ID 默认隐藏，助战编成可以关闭。Windows 使用本机保存对话框；安卓版图片直接保存到系统相册的“FGO抓包统计”，JSON 使用系统文件保存器。Android 7–9 首次保存图片需要存储权限，Android 10 及以上不申请存储权限。连续保存使用不同文件名，不覆盖已有图片。

## 扫码配置

固定协议参数统一填写在项目根目录的 `game-protocol.json`。本机这份文件不提交 Git，仓库只保留 [game-protocol.example.json](game-protocol.example.json) 模板。首次配置时复制模板并填写 `sdk_key`、`development_code`、`session_prefix`；源码运行和 APK 构建默认共用这一个文件。

正式 APK 内置构建时读取的应用级固定参数；这些参数不包含用户账号凭据。构建方法见 [ANDROID.md](ANDROID.md)。真实配置不进入源码提交，签名文件单独存放在仓库外。

桌面源码和项目目录内的 EXE 自动定位根目录配置，不再读取 AppData 中的旧加密缓存。单独移出的 EXE 读取同目录的 `game-protocol.json`，也可以通过 `--protocol 配置路径` 指定这份文件。修改后重启程序生效。普通 EXE 不内置真实参数；没有配置时仍能编译、导入文件和生成图片。

## 资源更新

启动时自动检查一次资源，点击“检查资源更新”可以再次检查。界面显示字典版本、文件数量、图片缓存数量、保存位置及当前进度。

字典来自 Chaldea 公共数据仓库、Atlas Academy 国服数据和 Chaldea 国服卡池补充表，覆盖统计所用的从者、礼装、卡池、关卡、技能、名称等数据。每次检查都查询上游清单，分片数量按新清单读取；没有变化的文件复用本机缓存。

Chaldea 文件按源站版本表核对大小及短 MD5，下载后记录完整 SHA-256；Atlas 国服版本和卡池补充表在下载前后复核。全部文件及统计加载器验证通过后才启用新版本。下载中断、源站同时更新或格式不兼容时继续使用旧版，重启后保留上次启用的版本。

出图所需的公开图片来自 Atlas Academy，按需下载并缓存，不下载整套游戏素材。切换字典版本后，图片缓存也使用新版本，避免相同地址继续沿用旧图。已有统计图需点击“重新生成统计图”才能使用新资源。

更新受公开数据源发布时间影响。登录协议、数据格式或页面代码变化需要更新程序，资源检查不下载或执行程序代码。

## 从源码运行

使用 Python 3.13、uv 和 WebView2 Runtime，在项目根目录执行：

```powershell
uv sync --extra desktop --group build --group dev
uv run python run_desktop.py
```

源码环境首次运行会从公开源准备字典和通用图片。已有完整资源可指定目录：

```powershell
uv run python run_desktop.py --resources C:\FGOResources
```

## 编译

Windows：

```powershell
uv run python tools/build_desktop.py --output dist\desktop-review
```

构建默认从公开源准备字典和通用图片。也可通过 `--resources C:\FGOResources` 使用已有的 `data`、`atlas-cn`、`assets` 目录；原生助战布局另需已核验的 `native-ui` 资源，未提供时使用标准布局。

`candidate` 目录只生成 `FGOStatDesktop.exe`。说明和各项许可证先按白名单收集，再编入 EXE；构建记录、输入副本和哈希清单留在构建工作目录，不随客户端提供。程序运行时将内置文件解包到临时目录，字典更新和图片缓存另存于当前用户的应用数据目录。

安卓使用 JDK 17、Android SDK 35、NDK 28.2、Gradle Wrapper 和 Chaquopy。原生依赖、外部协议配置、签名和 APK 复核步骤见 [ANDROID.md](ANDROID.md)。

构建目录、配置缓存、测试 APK 和日志不是客户端交付物。正式发布前检查完整文件范围与嵌套载荷，不要直接压缩仓库或日常运行目录。

## 代码目录

- `src/fgo_local_exporter/protocol.py`：官方扫码授权和游戏取数。
- `game_profile.py`：固定配置校验、统一文件位置与读取；`desktop_profile.py` 仅保留旧加密配置迁移兼容。
- `login_session.py`、`sessions.py`：扫码、导入、报告状态及内存期限。
- `statistics.py`、`import_worker.py`：输入限额、解析和统计字段提取。
- `resource_catalog.py`：公开源版本清单、地址限制与有界下载。
- `desktop_resources.py`：字典核验、版本切换和图片缓存。
- `reports.py`、`desktop_reports.py`：统计引擎装配与资源版本校验。
- `local_api.py`：随机回环端口上的本机接口。
- `desktop.py`、`desktop_bridge.py`：Windows 窗口与文件操作。
- `mobile.py`、`android/`：安卓运行时、系统文件选择器与相册保存。
- `ui/`、`desktop_static/`、`mobile_static/`：共用界面及各端交互。
- `src/fgo_stat_core/`：数据模型、解析器、统计计算、报告模板和助战组件。
- `tools/`：构建、资源白名单和发布复核脚本。
- `tests/`：人工构造数据的解析、会话、更新和发布范围测试。

统计公式和模板由 `fgo_stat_core` 统一提供，界面不重复计算。

## 检查与实测

```powershell
uv run ruff check src tests tools run_desktop.py
uv run pytest -q
```

当前源码通过 196 项测试。0.4.2 已在 Windows、雷电 Android 9 上运行，实际验证 APK 的 iOS 区服扫码取数、文件导入、统计图生成、JSON 保存和图片直接保存相册。统一配置入口另有读取、校验、路径与排除规则测试。完整记录及未验证范围见 [VALIDATION.md](VALIDATION.md)。模拟器通过不代表所有手机兼容。

## 数据处理与许可

登录凭据与原始响应只在内存中处理，不进入日志、磁盘或数据库。统计和报告最多保留 10 分钟，也可立即清除。主动保存的统计文件、相册图片和公开资源缓存保留在设备上；导出文件不含登录凭据，可能含角色名等个人信息，请自行保管。

本工具与《Fate/Grand Order》、bilibili 及相关运营方无关联，不属于官方服务。本项目代码采用 MIT，见 [LICENSE](LICENSE)；游戏素材、图标、字体、第三方数据与依赖各自保留原权利及许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
