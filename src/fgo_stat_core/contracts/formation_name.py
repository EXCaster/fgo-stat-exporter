"""助战编队名的显式文本边界；不是通用自由文本白名单。"""

import unicodedata

__all__ = ["validate_formation_name"]


def validate_formation_name(value: object) -> str:
    """保留显式空串；不截断、替换或规范化用户名称。"""
    # 本工具的资源/显示边界，并非声称游戏服务端的名称长度限制。
    if (
        not isinstance(value, str)
        or len(value) > 64
        or any(unicodedata.category(char)[0] == "C" or char in "\u2028\u2029" for char in value)
        or len(value.encode("utf-8")) > 256
    ):
        raise ValueError("FORMATION_NAME_INVALID")
    return value
