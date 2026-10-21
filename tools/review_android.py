"""复核 APK 的完整载荷、嵌套归档和编译模块；发现越界文件即拒绝发布。"""

import argparse
import hashlib
import io
import json
import marshal
import struct
import zipfile
from pathlib import Path, PurePosixPath

from prepare_android import DATA, MODULES, ROOT
from release_parts.runtime import CORE_DATA, CORE_MODULES

from fgo_local_exporter.game_profile import checked_profile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def check_name(name):
    parts = PurePosixPath(name).parts
    if (
        name.startswith(("/", "\\"))
        or ".." in parts
        or "\\" in name
        or {"test", "tests", "__tests__", "SelfTest", ".git"}.intersection(parts)
        or name.endswith(
            (
                ".py",
                ".pyi",
                ".pyx",
                ".pxd",
                ".c",
                ".h",
                ".map",
                ".pdb",
                ".jks",
                ".keystore",
                ".p12",
                ".dpapi",
                ".env",
                ".log",
            )
        )
    ):
        raise RuntimeError("APK 中存在非运行文件：" + name)


def check_elf(raw, name):
    if raw[4:6] != b"\x02\x01":
        raise RuntimeError("APK 包含非预期架构：" + name)
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    entry, count = struct.unpack_from("<HH", raw, 54)
    for i in range(count):
        offset = phoff + i * entry
        if struct.unpack_from("<I", raw, offset)[0] == 1:
            if struct.unpack_from("<Q", raw, offset + 48)[0] < 16384:
                raise RuntimeError("原生库不满足 16 KB 页对齐：" + name)
    shoff = struct.unpack_from("<Q", raw, 40)[0]
    size, count, index = struct.unpack_from("<HHH", raw, 58)
    start, length = struct.unpack_from("<QQ", raw, shoff + size * index + 24)
    strings = raw[start : start + length]
    for i in range(count):
        position = struct.unpack_from("<I", raw, shoff + i * size)[0]
        section = strings[position : strings.find(b"\0", position)]
        if section.startswith((b".debug_", b".zdebug_")):
            raise RuntimeError("原生库夹带调试符号：" + name)


def scan_archive(raw, *, prefix="", depth=0):
    if depth > 3:
        raise RuntimeError("APK 嵌套归档层数异常")
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 12000:
            raise RuntimeError("APK 归档路径重复或数量异常")
        if sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
            raise RuntimeError("APK 归档解压体积异常")
        for item in archive.infolist():
            check_name(item.filename)
            if item.is_dir():
                continue
            name = prefix + item.filename
            payload = archive.read(item)
            files[name] = digest(payload)
            if payload.startswith(b"PK\x03\x04"):
                files.update(scan_archive(payload, prefix=name + "!/", depth=depth + 1))
            if payload.startswith(b"\x7fELF"):
                check_elf(payload, name)
    return files


def review(apk_path, prepared):
    sources = {"fgo_local_exporter/" + name + ".py" for name in MODULES}
    sources.update("fgo_stat_core/" + name for name in CORE_MODULES)
    resources = {"fgo_local_exporter/" + name for name in DATA}
    resources.update("fgo_stat_core/" + name for name in CORE_DATA)
    staged = {
        path.relative_to(prepared / "python").as_posix()
        for path in (prepared / "python").rglob("*")
        if path.is_file()
    }
    if staged != sources | resources:
        raise RuntimeError("安卓输入目录与源码、资源白名单不符")
    for name in staged:
        if (prepared / "python" / name).read_bytes() != (ROOT / "src" / name).read_bytes():
            raise RuntimeError("构建材料不是当前审核版本：" + name)
    raw = apk_path.read_bytes()
    inventory = scan_archive(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as apk:
        expected_assets = {
            "assets/" + path.relative_to(prepared / "assets").as_posix(): digest(path.read_bytes())
            for path in (prepared / "assets").rglob("*")
            if path.is_file()
        }
        actual_assets = {
            name: digest(apk.read(name))
            for name in apk.namelist()
            if name.startswith("assets/")
            and not name.startswith("assets/chaquopy/")
            and not name.endswith("/")
        }
        if expected_assets != actual_assets:
            raise RuntimeError("APK 资源载荷与暂存白名单不符")
        if "assets/game-protocol.json" in actual_assets:
            checked_profile(json.loads(apk.read("assets/game-protocol.json")))
        with zipfile.ZipFile(io.BytesIO(apk.read("assets/chaquopy/app.imy"))) as app:
            expected = {name.removesuffix(".py") + ".pyc" for name in sources} | resources
            actual = {item.filename for item in app.infolist() if not item.is_dir()}
            if expected != actual:
                raise RuntimeError("APK 编译模块与审核清单不符")
            for name in resources:
                if app.read(name) != (prepared / "python" / name).read_bytes():
                    raise RuntimeError("APK 页面或资源哈希不符：" + name)
            for name in sources:
                code = marshal.loads(app.read(name[:-3] + ".pyc")[16:])
                source = (prepared / "python" / name).read_bytes()
                if code != compile(source, code.co_filename, "exec", dont_inherit=True):
                    raise RuntimeError("APK 编译内容不符：" + name)
        public = json.loads(apk.read("assets/public-manifest.json"))
        with zipfile.ZipFile(io.BytesIO(apk.read("assets/public-resources.zip"))) as archive:
            actual = {item.filename: digest(archive.read(item)) for item in archive.infolist()}
            if actual != public:
                raise RuntimeError("APK 公开资源集合与哈希不符")
    return {"apk_sha256": digest(raw), "apk_bytes": len(raw), "files": inventory}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.apk, args.prepared)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"APK 完整复核通过：{len(result['files'])} 个载荷，{result['apk_bytes']} 字节")


if __name__ == "__main__":
    main()
