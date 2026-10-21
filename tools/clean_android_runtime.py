"""只清理安卓构建目录内的依赖测试和开发文件，保留运行代码及许可。"""

import sys
from pathlib import Path


def excluded(path):
    return (
        path.suffix in {".pyi", ".c", ".h", ".pyx", ".pxd", ".map", ".pdb"}
        or path.name == "py.typed"
        or bool({"SelfTest", "tests", "test", "__tests__"}.intersection(path.parts))
    )


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    app_build = Path(__file__).resolve().parents[1] / "android/app/build"
    if not root.is_relative_to(app_build.resolve()) or root.name not in {"debug", "release"}:
        raise SystemExit("清理目标不在本项目的依赖构建目录中")
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and excluded(path):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise RuntimeError("依赖文件越出清理范围")
            path.unlink()
            removed += 1
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    print(f"已排除 {removed} 个依赖开发文件")


if __name__ == "__main__":
    main()
