"""发布规则覆盖所有依赖的测试目录，不依赖包名枚举。"""

import importlib.util
from pathlib import Path


def test_android_dependency_cleaner_excludes_all_test_directories():
    script = Path(__file__).parents[1] / "tools/clean_android_runtime.py"
    spec = importlib.util.spec_from_file_location("android_release_cleaner", script)
    cleaner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cleaner)
    for name in (
        "certifi/tests/test_certify.pyc",
        "Crypto/SelfTest/Cipher/test_AES.pyc",
        "new_dependency/test/capture.json",
        "another/__tests__/fixture.json",
        "extension/source.c",
        "extension/debug.pdb",
    ):
        assert cleaner.excluded(Path(name))
    for name in (
        "certifi/cacert.pem",
        "certifi/core.pyc",
        "Crypto/Cipher/AES.pyc",
        "certifi-1.0.dist-info/licenses/LICENSE",
        "fgo_local_exporter/desktop_resources.pyc",
    ):
        assert not cleaner.excluded(Path(name))
