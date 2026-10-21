"""原生数字图集排版，使用明确的字形度量，不从像素外观反推间距。"""

from typing import Any

from PIL import Image


class NativeBitmapFont:
    def __init__(self, data: dict[str, Any], texture: Image.Image) -> None:
        self.size = data["mSize"]
        self.base = data["mBase"]
        self.texture = texture.convert("RGBA")
        self.glyphs = {chr(g["index"]): g for g in data["mSaved"]}

    def layout(self, text: str, font_size: float, spacing: float) -> dict[str, Any]:
        """间距使用已应用 NGUI 缩放后的原生单位。"""
        x = 0
        glyphs = []
        s = font_size / self.size
        for c in text:
            if c not in self.glyphs:
                raise ValueError(f"No native glyph for {c!r}")
            g = self.glyphs[c]
            glyphs.append(
                (c, g, x + g["offsetX"] * s, g["offsetY"] * s, g["width"] * s, g["height"] * s)
            )
            x += g["advance"] * s + spacing
        return {
            "width": max(0, x - spacing),
            "height": font_size,
            "glyphs": glyphs,
            "font_scale": s,
        }

    def image(
        self, text: str, font_size: float, spacing: float, pixel_scale: float = 4
    ) -> tuple[Image.Image, dict[str, Any]]:
        q = self.layout(text, font_size, spacing)
        right = max([q["width"]] + [x + w for _, g, x, y, w, h in q["glyphs"]])
        bottom = max([q["height"]] + [y + h for _, g, x, y, w, h in q["glyphs"]])
        out = Image.new(
            "RGBA", (max(1, round(right * pixel_scale)), max(1, round(bottom * pixel_scale)))
        )
        for _c, g, x, y, w, h in q["glyphs"]:
            crop = self.texture.crop((g["x"], g["y"], g["x"] + g["width"], g["y"] + g["height"]))
            crop = crop.resize(
                (max(1, round(w * pixel_scale)), max(1, round(h * pixel_scale))),
                Image.Resampling.LANCZOS,
            )
            out.alpha_composite(crop, (round(x * pixel_scale), round(y * pixel_scale)))
        return out, q
