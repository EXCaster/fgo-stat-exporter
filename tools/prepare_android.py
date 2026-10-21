"""按白名单暂存安卓材料；默认使用项目根目录的本机固定协议配置。"""

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
from release_parts.resources import copy_resources, prepared_resources  # noqa: E402
from release_parts.runtime import CORE_DATA, CORE_MODULES  # noqa: E402

from fgo_local_exporter.game_profile import load_profile, profile_values  # noqa: E402

MODULES = (
    "__init__",
    "errors",
    "game_profile",
    "protocol",
    "statistics",
    "login_session",
    "local_api",
    "settings",
    "reports",
    "sessions",
    "desktop_reports",
    "desktop_resources",
    "resource_catalog",
    "mobile",
)
DATA = (
    "ui/index.html",
    "ui/style.css",
    "ui/app.js",
    "ui/html-to-image.js",
    "ui/resource-status.js",
    "desktop_static/setup.html",
    "desktop_static/desktop.css",
    "desktop_static/resources.json",
    "mobile_static/mobile.js",
    "mobile_static/mobile.css",
)


def build_profile(path=None):
    selected = Path(path) if path is not None else ROOT / "game-protocol.json"
    profile = load_profile(selected)
    if path is not None and profile is None:
        raise RuntimeError("指定的游戏固定配置文件不存在")
    return profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, help="指定其他配置，默认读取项目根目录配置")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("输出目录已存在，请选择新的空目录")
    profile = build_profile(args.protocol)
    paths = ["fgo_local_exporter/" + name + ".py" for name in MODULES]
    paths += ["fgo_local_exporter/" + name for name in DATA]
    paths += ["fgo_stat_core/" + name for name in (*CORE_MODULES, *CORE_DATA)]
    hashes = {}
    for name in paths:
        source = ROOT / "src" / name
        if not source.is_file() or source.is_symlink():
            raise RuntimeError("安卓输入不合法：" + name)
        target = args.output / "python" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    assets = args.output / "assets"
    assets.mkdir()
    if profile is not None:
        (assets / "game-protocol.json").write_text(
            json.dumps(profile_values(profile), separators=(",", ":")), encoding="utf-8"
        )
    license_dir = assets / "licenses"
    license_dir.mkdir()
    for source, name in (
        (ROOT / "LICENSE", "project-MIT.txt"),
        (ROOT / "licenses/html-to-image-MIT.txt", "html-to-image-MIT.txt"),
        (ROOT / "licenses/Chaquopy-MIT.txt", "Chaquopy-MIT.txt"),
        (ROOT / "licenses/Python-3.13.txt", "Python-3.13.txt"),
        (ROOT / "licenses/OpenSSL-Apache-2.0.txt", "OpenSSL-Apache-2.0.txt"),
    ):
        shutil.copyfile(source, license_dir / name)
    resources = args.output / "reviewed-public-resources"
    public = copy_resources(
        prepared_resources(args.resources), resources, ROOT / "src/fgo_stat_core"
    )
    with zipfile.ZipFile(assets / "public-resources.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(public):
            archive.write(resources / name, name)
    (assets / "public-manifest.json").write_text(json.dumps(public, indent=2))
    with zipfile.ZipFile(assets / "public-resources.zip") as archive:
        reviewed = {
            name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
        }
        if reviewed != public:
            raise RuntimeError("安卓公开资源归档复核失败")
    icon = Image.open(ROOT / "assets/app.ico").convert("RGBA")
    for density, size in (
        ("mdpi", 48),
        ("hdpi", 72),
        ("xhdpi", 96),
        ("xxhdpi", 144),
        ("xxxhdpi", 192),
    ):
        target = ROOT / f"android/app/src/main/res/mipmap-{density}/ic_launcher.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        icon.resize((size, size), Image.Resampling.LANCZOS).save(target)
    (args.output / "source-review.json").write_text(json.dumps(hashes, indent=2))
    print("安卓构建材料已准备：" + str(args.output), flush=True)


if __name__ == "__main__":
    main()
