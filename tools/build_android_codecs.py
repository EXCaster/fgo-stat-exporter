"""重建兼容 16 KB 内存页的字体和图片依赖，并保留上游许可。"""

import argparse
import base64
import csv
import hashlib
import io
import os
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

SOURCES = {
    "freetype-2.14.1": (
        "https://github.com/freetype/freetype/archive/refs/tags/VER-2-14-1.tar.gz",
        "44bd69d1f0750603410cfd4f26f1c5523c5a3a087a2dfa8639b757dc7c6677be",
    ),
    "libjpeg-turbo-3.2.0": (
        "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/3.2.0/"
        "libjpeg-turbo-3.2.0.tar.gz",
        "6f30092cef9fb839779646608f4ee14ae3cbac989c47fa05e841b0841f09878e",
    ),
}


def fetch(root, name):
    url, digest = SOURCES[name]
    archive = root / (name + ".tar.gz")
    if not archive.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            archive.write_bytes(response.read(32 * 1024 * 1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise RuntimeError("上游源码校验失败：" + name)
    target = root / name
    if not target.exists():
        target.mkdir()
        with tarfile.open(archive) as content:
            for member in content.getmembers():
                parts = Path(member.name).parts
                if len(parts) > 1:
                    member.name = str(Path(*parts[1:]))
                    content.extract(member, target, filter="data")
    return target


def package(output, name, version, abi, library, library_name, licenses, summary):
    tag = "py3-none-android_24_" + abi.replace("-", "_")
    info = f"{name}-{version}.dist-info/"
    entries = {"chaquopy/lib/" + library_name: library.read_bytes()}
    entries[info + "METADATA"] = (
        f"Metadata-Version: 2.4\nName: {name.replace('_', '-')}\nVersion: {version}\n"
        f"Summary: {summary}\n"
    ).encode()
    entries[info + "WHEEL"] = (
        f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nGenerator: local-android-build\nTag: {tag}\n"
    ).encode()
    for path in licenses:
        entries[info + "licenses/" + path.name] = path.read_bytes()
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for relative, raw in sorted(entries.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        writer.writerow((relative, "sha256=" + digest, len(raw)))
    writer.writerow((info + "RECORD", "", ""))
    entries[info + "RECORD"] = record.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{name}-{version}-{tag}.whl"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, raw in entries.items():
            archive.writestr(relative, raw)
    print("已生成：" + str(target), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    freetype = fetch(args.work, "freetype-2.14.1")
    jpeg = fetch(args.work, "libjpeg-turbo-3.2.0")
    # 仅调整动态库名称，与 Pillow 的加载名称保持一致。
    patch = (
        "\nif(TARGET jpeg)\n"
        "  set_target_properties(jpeg PROPERTIES OUTPUT_NAME jpeg_chaquopy)\nendif()\n"
    )
    cmake_source = jpeg / "CMakeLists.txt"
    text = cmake_source.read_text()
    if patch not in text:
        cmake_source.write_text(text + patch)
    host = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
    strip = (
        args.ndk
        / "toolchains/llvm/prebuilt"
        / host
        / "bin"
        / ("llvm-strip.exe" if os.name == "nt" else "llvm-strip")
    )
    for abi in ("arm64-v8a", "x86_64"):
        for kind, source in (("freetype", freetype), ("jpeg", jpeg)):
            build = args.work / (kind + "-" + abi)
            command = [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(build),
                "-G",
                "Ninja",
                "-DCMAKE_TOOLCHAIN_FILE=" + str(args.ndk / "build/cmake/android.toolchain.cmake"),
                "-DANDROID_ABI=" + abi,
                "-DANDROID_PLATFORM=android-24",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DBUILD_SHARED_LIBS=ON",
                "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384",
            ]
            if kind == "freetype":
                command += [
                    "-DFT_DISABLE_" + value + "=ON"
                    for value in ("BZIP2", "PNG", "HARFBUZZ", "BROTLI")
                ]
            else:
                command += [
                    "-DENABLE_SHARED=ON",
                    "-DENABLE_STATIC=OFF",
                    "-DWITH_TURBOJPEG=OFF",
                    "-DWITH_TOOLS=OFF",
                    "-DWITH_TESTS=OFF",
                    "-DWITH_SIMD=OFF",
                ]
            with (args.work / (kind + "-" + abi + ".log")).open("wb") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run(
                    ["cmake", "--build", str(build), "--parallel", "8"],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            name = "libfreetype.so" if kind == "freetype" else "libjpeg_chaquopy.so"
            library = build / name
            subprocess.run([str(strip), "--strip-unneeded", str(library)], check=True)
            if kind == "freetype":
                package(
                    args.output,
                    "chaquopy_freetype",
                    "2.9.1+ft2.14.1.16k",
                    abi,
                    library,
                    name,
                    [freetype / "docs/FTL.TXT"],
                    "FreeType 2.14.1; Android 16 KB page build",
                )
            else:
                package(
                    args.output,
                    "chaquopy_libjpeg",
                    "1.5.3+turbo3.2.0.16k",
                    abi,
                    library,
                    name,
                    [jpeg / "LICENSE.md", jpeg / "README.ijg"],
                    "libjpeg-turbo 3.2.0; Android 16 KB page build",
                )


if __name__ == "__main__":
    main()
