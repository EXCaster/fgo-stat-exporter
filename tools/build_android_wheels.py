"""用固定版本的上游源码交叉编译安卓校验库，不修改统计模型。"""

import argparse
import base64
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "2.50.1"
SOURCE = (
    "https://files.pythonhosted.org/packages/a6/24/"
    "af4ec4be49fbc810f35b0bdcacc3d433b56bbfa469fd3bfd4ae116cd9bf1/"
    "pydantic_core-2.50.1.tar.gz"
)
SOURCE_SHA = "e50d7b94baac6c7d09927fa5ca5800a0c7ee5015c7fcff65beb3a1931b5a6e09"
TARGETS = {"arm64_v8a": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
RUNTIME_HASHES = {
    "arm64-v8a": "fae8cfd4d3910b6f978b22279fe820c0c6ba49d0ea20f7b106aa6130f1c8f355",
    "x86_64": "77a6a3325aff0a171c36c11c8c3b2204a53783a3d42c29cff10a5ddecee5bfb6",
}


def prepare_runtime(work):
    output = work / "python-libs"
    for abi, digest in RUNTIME_HASHES.items():
        name = f"target-3.13.16-0-{abi}.zip"
        archive = work / name
        if not archive.exists():
            url = "https://repo.maven.apache.org/maven2/com/chaquo/python/target/3.13.16-0/"
            with urllib.request.urlopen(url + name, timeout=90) as response:
                archive.write_bytes(response.read(64 * 1024 * 1024))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise RuntimeError("安卓 Python 运行库校验失败")
        with zipfile.ZipFile(archive) as content:
            target = output / abi / "libpython3.13.so"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.read(f"jniLibs/{abi}/libpython3.13.so"))
    return output


def wheel(source, output, abi, target):
    entries = {}
    for path in (source / "python/pydantic_core").iterdir():
        if path.is_file() and path.suffix in {".py", ".pyi", ".typed"}:
            entries["pydantic_core/" + path.name] = path.read_bytes()
    library = source / f"target/{target}/release/lib_pydantic_core.so"
    entries["pydantic_core/_pydantic_core.so"] = library.read_bytes()
    info = f"pydantic_core-{VERSION}.dist-info/"
    tag = f"cp313-cp313-android_24_{abi}"
    entries[info + "METADATA"] = (
        f"Metadata-Version: 2.4\nName: pydantic_core\nVersion: {VERSION}\n"
        "License-Expression: MIT\nRequires-Python: >=3.10\n"
        "Requires-Dist: typing-extensions>=4.16.0\n"
    ).encode()
    entries[info + "WHEEL"] = (
        f"Wheel-Version: 1.0\nGenerator: local-android-build\nRoot-Is-Purelib: false\nTag: {tag}\n"
    ).encode()
    entries[info + "licenses/LICENSE"] = (source / "LICENSE").read_bytes()
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, raw in sorted(entries.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(raw)))
    writer.writerow((info + "RECORD", "", ""))
    entries[info + "RECORD"] = record.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"pydantic_core-{VERSION}-{tag}.whl"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries.items():
            archive.writestr(name, raw)
    print("已生成：" + str(path), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--python-libs", type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        raise SystemExit("需要 Python 3.13")
    args.work.mkdir(parents=True, exist_ok=True)
    python_libs = args.python_libs or prepare_runtime(args.work)
    archive = args.work / f"pydantic_core-{VERSION}.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(SOURCE, timeout=90) as response:
            archive.write_bytes(response.read(8 * 1024 * 1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("上游源码校验失败")
    source = args.source or args.work / f"pydantic_core-{VERSION}"
    if not source.exists():
        with tarfile.open(archive) as content:
            content.extractall(args.work, filter="data")
    config = args.work / "python-android.conf"
    config.write_text(
        "implementation=CPython\nversion=3.13\nshared=true\nabi3=false\n"
        "pointer_width=64\nbuild_flags=\nsuppress_build_script_link_lines=true\n"
    )
    host = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
    toolchain = args.ndk / "toolchains/llvm/prebuilt" / host / "bin"
    for abi, target in TARGETS.items():
        env = dict(os.environ, PYO3_CONFIG_FILE=str(config.resolve()), PYO3_PYTHON=sys.executable)
        env["CARGO_TARGET_" + target.upper().replace("-", "_") + "_LINKER"] = str(
            toolchain / (target + "24-clang" + (".cmd" if os.name == "nt" else ""))
        )
        android_abi = "arm64-v8a" if abi == "arm64_v8a" else "x86_64"
        python_library = python_libs / android_abi / "libpython3.13.so"
        if not python_library.is_file():
            raise RuntimeError("缺少对应架构的 Chaquopy Python 动态库")
        command = [
            shutil.which("cargo") or "cargo",
            "rustc",
            "--release",
            "--locked",
            "--target",
            target,
            "--features",
            "pyo3/extension-module",
            "--lib",
            "--",
            "-C",
            "link-arg=" + str(python_library.resolve()),
        ]
        subprocess.run(command, cwd=source, env=env, check=True)
        wheel(source, args.output, abi, target)


if __name__ == "__main__":
    main()
