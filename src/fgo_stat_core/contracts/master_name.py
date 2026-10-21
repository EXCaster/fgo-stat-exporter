"""御主游戏昵称的独立白名单边界，不允许扩展到其他账号自由文本。"""

import unicodedata

__all__ = ["validate_master_name"]


def validate_master_name(value: object) -> str:
    """保留原始 Unicode 和显式空串；不截断、替换或规范化昵称。"""
    # 这是本工具的显示/资源边界，并非声称游戏服务端的长度限制。
    # 字母、组合标记、数字、标点、符号和普通空格分隔符均可作纯文本。
    # 排除控制/格式/代理/私用/未分配字符及行/段落分隔符。
    if (
        not isinstance(value, str)
        or len(value) > 64
        or any(
            unicodedata.category(char)[0] not in "LMNPS" and unicodedata.category(char) != "Zs"
            for char in value
        )
        or len(value.encode("utf-8")) > 256
    ):
        raise ValueError("MASTER_NAME_INVALID")
    return value
