"""有界解码，不记录输入，不执行用户内容。"""

import base64
import binascii
import json
import re
import time
import zlib
from urllib.parse import unquote_to_bytes

from fgo_stat_core.contracts.models import CaptureError, Limits

__all__ = ["decode_capture"]


def _inflate(data: bytes, mode: int, limit: int) -> bytes:
    decoder = zlib.decompressobj(mode)
    result = decoder.decompress(data, limit + 1)
    if len(result) > limit or decoder.unconsumed_tail:
        raise CaptureError("DECODED_TOO_LARGE")
    if not decoder.eof or decoder.unused_data:
        raise CaptureError("COMPRESSION_INVALID")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise CaptureError("JSON_INVALID")


def _check_depth(text: str, limits: Limits, deadline: float) -> None:
    depth = 0
    in_string = escaped = in_atom = False
    nodes = 0
    for index, char in enumerate(text):
        if index % 65536 == 0 and time.monotonic() > deadline:
            raise CaptureError("PARSE_TIMEOUT")
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            in_atom = False
            nodes += 1
        elif char in "[{":
            in_atom = False
            nodes += 1
            depth += 1
            if depth > limits.max_depth:
                raise CaptureError("STRUCTURE_TOO_DEEP")
        elif char in "]}":
            depth -= 1
            in_atom = False
        elif char in ",: \r\n\t":
            in_atom = False
        elif not in_atom:
            nodes += 1
            in_atom = True
        if nodes > limits.max_nodes:
            raise CaptureError("TOO_MANY_NODES")


def decode_capture(raw: bytes, limits: Limits) -> dict[str, object]:
    if not raw:
        raise CaptureError("INPUT_EMPTY")
    if len(raw) > limits.input_bytes:
        raise CaptureError("INPUT_TOO_LARGE")
    deadline = time.monotonic() + limits.parse_seconds
    data = raw
    for layer in range(limits.max_layers + 1):
        if len(data) > limits.decoded_bytes:
            raise CaptureError("DECODED_TOO_LARGE")
        if time.monotonic() > deadline:
            raise CaptureError("PARSE_TIMEOUT")
        stripped = data.lstrip(b"\xef\xbb\xbf \r\n\t")
        if stripped.startswith(b"{"):
            try:
                text = data.decode("utf-8-sig")
                _check_depth(text, limits, deadline)
                parsed: object = json.loads(
                    text, object_pairs_hook=_pairs, parse_constant=_constant
                )
            except (ValueError, UnicodeError, RecursionError):
                raise CaptureError("JSON_INVALID") from None
            if not isinstance(parsed, dict):
                raise CaptureError("STRUCTURE_INVALID")
            stack: list[object] = [parsed]
            nodes = 0
            while stack:
                node = stack.pop()
                nodes += 1
                if nodes > limits.max_nodes:
                    raise CaptureError("TOO_MANY_NODES")
                if nodes % 4096 == 0 and time.monotonic() > deadline:
                    raise CaptureError("PARSE_TIMEOUT")
                if isinstance(node, dict):
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
            return parsed
        if layer == limits.max_layers:
            break
        try:
            if data.startswith(b"\x1f\x8b"):
                data = _inflate(data, 31, limits.decoded_bytes)
            elif len(data) > 1 and data[0] & 15 == 8 and int.from_bytes(data[:2]) % 31 == 0:
                data = _inflate(data, 15, limits.decoded_bytes)
            elif b"%" in data and all(byte in (9, 10, 13) or 32 <= byte <= 126 for byte in data):
                if re.search(rb"%(?![a-fA-F0-9]{2})", data):
                    raise CaptureError("ENCODING_INVALID")
                data = unquote_to_bytes(data)
            else:
                compact = re.sub(rb"\s+", b"", data)
                try:
                    data = base64.b64decode(compact, validate=True)
                except binascii.Error:
                    data = _inflate(data, -15, limits.decoded_bytes)
        except (ValueError, zlib.error):
            raise CaptureError("ENCODING_INVALID") from None
    raise CaptureError("FORMAT_UNSUPPORTED")
