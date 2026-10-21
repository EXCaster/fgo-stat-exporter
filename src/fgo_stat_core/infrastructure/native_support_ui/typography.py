"""助战数字与文字排版，不改变卡片、立绘、礼装和背景的变换。
原生数字图集先按标签字号采样，再应用一次父级缩放。
斜杠使用独立字形和步进宽度，不能覆盖数字。
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fgo_stat_core.infrastructure.report_fonts import report_font_path

from .bitmap_font import NativeBitmapFont

SCALE = 8
REGULAR = report_font_path("regular")


def _expand_alpha(image: Image.Image, radius: int) -> Image.Image:
    """将大方形最大值滤波分解为小核，保留相同边缘与像素结果。"""
    for _ in range(radius):
        image = image.filter(ImageFilter.MaxFilter(3))
    return image


def bitmap_line(
    text: str,
    size: float,
    bmf: NativeBitmapFont,
    spacing_x: float = 10,
    limit: float | None = None,
    outline: float = 1.0,
    regular_font: str | None = None,
) -> tuple[Image.Image, float, float, list[tuple[str, float, float, float, float]]]:
    scale = size / bmf.size
    cursor = 0.0
    cells = []
    previous_ink_right = None
    for ch in text:
        if ch == "/":
            # 原数字图集没有斜杠，单独排版分隔符，避免覆盖相邻数字。
            im = Image.new("RGBA", (80, 160))
            d = ImageDraw.Draw(im)
            d.text(
                (10, 0),
                "/",
                font=ImageFont.truetype(regular_font or REGULAR, 128),
                fill="white",
                anchor="lt",
            )
            bb = im.getbbox()
            im = im.crop(bb).resize(
                (round(size * 0.4375 * SCALE), round(size * 0.6875 * SCALE)),
                Image.Resampling.LANCZOS,
            )
            x = cursor + size * 0.25
            y = size * 0.15625
            advance = size * 0.75
        else:
            g = bmf.glyphs[ch]
            im = bmf.texture.crop((g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]))
            im = im.resize(
                (
                    max(1, round(g["width"] * scale * SCALE)),
                    max(1, round(g["height"] * scale * SCALE)),
                ),
                Image.Resampling.LANCZOS,
            )
            x = cursor + g["offsetX"] * scale
            y = g["offsetY"] * scale
            advance = (g["advance"] + spacing_x) * scale
        bb = im.getbbox()
        # 部分字形的可见区域超过其步进宽度，描边后仍须保留正间隙。
        if bb and previous_ink_right is not None:
            delta = max(0, previous_ink_right + 1.25 - (x + bb[0] / SCALE))
            x += delta
            cursor += delta
        cells.append((im, x, y, ch))
        cursor += advance
        if bb:
            previous_ink_right = x + bb[2] / SCALE
    extent = max([cursor] + [x + im.width / SCALE for im, x, y, ch in cells])
    canvas = Image.new("RGBA", (max(1, round((extent + 4) * SCALE)), round((size + 4) * SCALE)))
    boxes: list[tuple[str, float, float, float, float]] = []
    for im, x, y, ch in cells:
        xx = round((x + 2) * SCALE)
        yy = round((y + 2) * SCALE)
        canvas.alpha_composite(im, (xx, yy))
        bb = im.getbbox()
        if bb:
            boxes.append((ch, xx + bb[0], yy + bb[1], xx + bb[2], yy + bb[3]))
    # 字重修正与黑色描边分别处理，先分开字形再扩张，避免相邻数字粘连。
    alpha = canvas.getchannel("A")
    # 白色字形扩张控制在 0.375 个原生单位，分隔符使用独立单元。
    alpha = _expand_alpha(alpha, 3)
    white = Image.new("RGBA", canvas.size, "white")
    white.putalpha(alpha)
    canvas = white
    radius = max(0, round(outline * SCALE))
    if radius:
        black = Image.new("RGBA", canvas.size, "black")
        black.putalpha(_expand_alpha(alpha, radius))
        black.alpha_composite(canvas)
        canvas = black
    bbox = canvas.getbbox()
    if not bbox:
        return Image.new("RGBA", (1, 1)), 0, size, []
    # 保留左侧字形起点，只去掉右侧和底部的空白。
    right = max(bbox[2], 1)
    canvas = canvas.crop((0, 0, right, round((size + 4) * SCALE)))
    width = canvas.width / SCALE
    if limit and width > limit:
        ratio = limit / width
        canvas = canvas.resize((round(limit * SCALE), canvas.height), Image.Resampling.LANCZOS)
        boxes = [(ch, x1 * ratio, y1, x2 * ratio, y2) for ch, x1, y1, x2, y2 in boxes]
        width = limit
    return canvas, width, size + 4, boxes


def ink_line(
    text: str, size: float, bmf: NativeBitmapFont, kind: str, *, regular_font: str | None = None
) -> Image.Image:
    if kind == "level":
        im, w, h, _ = bitmap_line(text, size, bmf, 10, outline=1.0, regular_font=regular_font)
        bb = im.getbbox()
        return im.crop(bb)
    # 当前素材缺少 HP/ATK 原生字体，使用按可见高度量测的常规字重，
    # 不额外加粗或横向压缩。
    font = ImageFont.truetype(regular_font or REGULAR, round(size * SCALE))
    im = Image.new("RGBA", (1200, 300))
    d = ImageDraw.Draw(im)
    d.text((10, 10), text, font=font, fill="#ffed00", anchor="lt")
    im = im.crop(im.getbbox())
    h = size * 0.94 * SCALE
    factor = h / im.height
    return im.resize((max(1, round(im.width * factor)), max(1, round(h))), Image.Resampling.LANCZOS)
