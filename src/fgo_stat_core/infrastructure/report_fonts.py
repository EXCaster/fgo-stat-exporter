"""本机报告字体；优先使用已校验资源，其次使用系统字体。"""

import hashlib
import os
from pathlib import Path
from typing import Any, Literal

from fgo_stat_core.contracts.models import CaptureError

_FONTS = {
    "cjk": (
        "NotoSansCJK-Regular.ttc",
        "d18a3adba5c891eb7f9cdf8c31dad28dcc324db80e662d6a0f91e8db6aee5913",
    ),
    "regular": (
        "DejaVuSans.ttf",
        "f9a7bd58cdaa9d1e9acafd070db8dea0b6db9cf2b540501b15075315a47cba3d",
    ),
}


def report_font_path(key: Literal["cjk", "regular"]) -> str:
    name, digest = _FONTS[key]
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    folder = Path(os.environ.get("FGO_STATS_FONT_ROOT", base / "FGOStatExporter/resources/fonts"))
    path = folder / name
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 24 * 1024 * 1024:
            raise CaptureError("REPORT_FONT_CONFIG_INVALID")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise CaptureError("REPORT_FONT_CONFIG_INVALID")
        return str(path)
    if os.name == "nt":
        return str(
            Path(os.environ.get("WINDIR", "C:/Windows"))
            / "Fonts"
            / ("msyh.ttc" if key == "cjk" else "arial.ttf")
        )
    system = "opentype/noto/" + name if key == "cjk" else "truetype/dejavu/" + name
    return str(Path("/usr/share/fonts") / system)


def load_report_cjk_font(size: int) -> Any:
    """字典字体选择简体中文面；系统字体按其默认字面加载。"""
    from PIL import ImageFont

    path = report_font_path("cjk")
    return ImageFont.truetype(path, size, index=2 if Path(path).name == _FONTS["cjk"][0] else 0)
