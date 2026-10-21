"""只用人工昵称，覆盖提取、复验、旧快照与 HTML 文本安全。"""

import html
from dataclasses import replace
from datetime import date

import pytest
from pydantic import ValidationError

from fgo_stat_core.contracts.master_name import validate_master_name
from fgo_stat_core.contracts.models import CaptureError
from fgo_stat_core.contracts.report import AccountOverview
from fgo_stat_core.features.capture_import.parser import parse_capture, snapshot_json
from fgo_stat_core.features.report.calculator import build_report
from fgo_stat_core.infrastructure.report_ui import base_blocks, builder


def named_capture(root, name):
    tables = root["cache"]["replaced"]
    tables["userGame"][0].update(name=name, createdAt=1_600_000_000)
    tables["userLogin"] = [{"totalLoginCount": 123, "seqLoginCount": 4}]
    return root


def test_only_v2_name_survives_no_account_text_fallback(minimal_capture, encode_capture, hmac_key):
    root = named_capture(minimal_capture, "演示昵称")
    root["cache"]["replaced"]["userGame"][0].update(
        appname="DROP_PLATFORM_USERNAME",
        nickname="DROP_UNKNOWN_ALIAS",
        usk="DROP_CREDENTIAL",
        comment="DROP_COMMENT",
    )
    raw = encode_capture(root)
    old = parse_capture(raw, hmac_key)
    snapshot = parse_capture(raw, hmac_key, report_fields=True)
    assert "name" not in old.tables["userGame"][0]
    assert snapshot.tables["userGame"][0]["name"] == "演示昵称"
    assert "DROP_" not in snapshot_json(snapshot)


@pytest.mark.parametrize(
    "name",
    [
        None,
        1,
        True,
        [],
        {},
        "字" * 65,
        "😀" * 65,
        "bad\nname",
        "bad\rname",
        "bad\tname",
        "bad\x00name",
        "bad\x7fname",
        "bad\u0085name",
        "bad\u202ename",
        "bad\u2066name",
        "bad\u200bname",
        "bad\u2028name",
        "bad\u2029name",
        "bad\ud800name",
        "bad\ue000name",
    ],
)
def test_invalid_input_rejected_without_echo(minimal_capture, encode_capture, hmac_key, name):
    root = named_capture(minimal_capture, name)
    with pytest.raises(CaptureError, match="^FIELD_VALUE_INVALID$"):
        parse_capture(encode_capture(root), hmac_key, report_fields=True)
    with pytest.raises(ValueError, match="^MASTER_NAME_INVALID$"):
        validate_master_name(name)
    # None 在报告中表示缺项；仅抓包显式错误类型会拒绝。
    if name is not None:
        with pytest.raises(ValidationError) as exc:
            AccountOverview(created_day=date(2020, 1, 1), tenure_days=1, master_name=name)
        assert "bad" not in str(exc.value)


@pytest.mark.parametrize("name", ["<script>alert('x')</script>", '<img src=x onerror="x"> &'])
def test_html_treats_nickname_as_escaped_text(
    minimal_capture, encode_capture, hmac_key, tmp_path, name
):
    root = named_capture(minimal_capture, name)
    snapshot = parse_capture(encode_capture(root), hmac_key, report_fields=True)
    report = build_report(snapshot, None, generated_at=snapshot.captured_at)
    data = report.model_dump(mode="json")
    for output in (base_blocks.profile(data), builder.build(data, asset_dir=tmp_path)):
        assert "<h2>" + html.escape(name, quote=True) in output
        assert name not in output
        assert '<div class="avatar">M</div>' in output
        assert "<h2>御主 · " not in output


def test_direct_report_rechecks_nickname(minimal_capture, encode_capture, hmac_key):
    root = named_capture(minimal_capture, "演示昵称")
    snapshot = parse_capture(encode_capture(root), hmac_key, report_fields=True)
    game = {**snapshot.tables["userGame"][0], "name": "bad\nname"}
    invalid = replace(snapshot, tables={**snapshot.tables, "userGame": (game,)})
    with pytest.raises(CaptureError, match="^REPORT_DATA_INVALID$"):
        build_report(invalid, None, generated_at=snapshot.captured_at)
