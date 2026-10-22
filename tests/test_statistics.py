import base64
import copy
import gzip
import json

import pytest

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.statistics import decode_response, export_statistics


@pytest.fixture
def sample():
    # 人工构造；不是账号、抓包或实际响应。
    return {
        "response": [
            {
                "nid": "login",
                "resCode": "00",
                "success": {"session": "synthetic-session-do-not-export"},
                "usk": "synthetic-usk",
            }
        ],
        "cache": {
            "serverTime": 1700000000,
            "replaced": {
                "userGame": [
                    {
                        "userId": 123,
                        "friendCode": "123456789012",
                        "rkchannel": 24,
                        "name": "测试",
                        "lv": 1,
                        "cookie": "synthetic-cookie",
                    }
                ],
                "userSvt": [{"id": 1, "svtId": 800100, "lv": 1, "token": "synthetic-token"}],
                "userSvtCollection": [{"svtId": 800100}],
                "unknownTable": [{"password": "synthetic-password"}],
            },
            "updated": {"userLogin": [{"totalLoginCount": 2, "session": "synthetic-session"}]},
        },
    }


def test_only_statistics_survive_and_missing_optional_tables_stay_missing(sample):
    body, preview = export_statistics(sample)
    clean = json.loads(body)
    assert b"synthetic-" not in body
    assert "userItem" not in clean["cache"]["replaced"]
    assert "userItem" in preview["missing_tables"]
    assert "unknownTable" not in clean["cache"]["replaced"]
    assert clean["cache"]["updated"]["userLogin"] == [{"totalLoginCount": 2}]
    assert clean["response"] == [{"nid": "login", "resCode": "00", "success": {}}]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r["response"][0].update(resCode="88"), "STATISTICS_LOGIN_REQUIRED"),
        (
            lambda r: r["response"].append(copy.deepcopy(r["response"][0])),
            "STATISTICS_LOGIN_REQUIRED",
        ),
        (
            lambda r: r["cache"]["replaced"]["userSvt"][0].update(userId=999),
            "STATISTICS_ACCOUNT_INVALID",
        ),
        (
            lambda r: r["cache"]["replaced"]["userGame"][0].update(rkchannel=1000),
            "STATISTICS_REGION_UNSUPPORTED",
        ),
        (
            lambda r: r["cache"]["replaced"]["userSvt"][0].update(lv={"token": "synthetic"}),
            "STAT_FIELD_USERSVT_LV",
        ),
        (lambda r: r["cache"]["replaced"].pop("userSvt"), "STATISTICS_CORE_TABLES_MISSING"),
    ],
)
def test_rejects_failures_and_mixed_accounts(sample, mutation, code):
    mutation(sample)
    with pytest.raises(ExportError, match=code):
        export_statistics(sample)


def test_nested_support_fields_exclude_unknown_values(sample):
    sample["cache"]["replaced"]["userSvtGrand"] = [
        {
            "grandGraphId": 1,
            "userSvtId": 1,
            "equipTarget1": {"svtId": 100, "token": "synthetic-token"},
            "appendPassiveSkill": [{"skillId": 10, "skillLv": 3, "usk": "synthetic-usk"}],
            "script": {"equipTarget2SkillChange": 1, "password": "synthetic-password"},
        }
    ]
    body, _ = export_statistics(sample)
    assert b"synthetic-" not in body
    assert json.loads(body)["cache"]["replaced"]["userSvtGrand"][0]["script"] == {
        "equipTarget2SkillChange": 1
    }


def test_decode_compatible_layers_and_duplicate_field_rejection(sample):
    body = json.dumps(sample).encode()
    assert decode_response(base64.b64encode(gzip.compress(body))) == sample
    with pytest.raises(ExportError, match="RESPONSE_DUPLICATE_FIELD"):
        decode_response(b'{"cache":{},"cache":{}}')
    with pytest.raises(ExportError, match="RESPONSE_LIMIT"):
        decode_response(gzip.compress(b"A" * (32 * 1024 * 1024 + 1)))


def test_deep_unknown_input_is_rejected_before_export(sample):
    nested = {}
    sample["unknown"] = nested
    for _ in range(40):
        child = {}
        nested["x"] = child
        nested = child
    with pytest.raises(ExportError, match="RESPONSE_LIMIT"):
        export_statistics(sample)


def test_optional_null_fields_are_missing_not_zero(sample):
    row = sample["cache"]["replaced"]["userSvt"][0]
    row.update(lv=None, hp=None, transformVal=None)
    sample["cache"]["replaced"]["userSvtCollection"][0]["costumeIds"] = None
    body, _ = export_statistics(sample)
    clean = json.loads(body)["cache"]["replaced"]
    assert clean["userSvt"][0] == {"id": 1, "svtId": 800100}
    assert "costumeIds" not in clean["userSvtCollection"][0]


def test_required_null_field_keeps_strict_validation(sample):
    sample["cache"]["replaced"]["userSvt"][0]["svtId"] = None
    with pytest.raises(ExportError, match="^STAT_FIELD_USERSVT_SVTID$"):
        export_statistics(sample)


@pytest.mark.parametrize("script", [None, [], {}])
def test_empty_grand_optional_sections_remain_missing(sample, script):
    sample["cache"]["replaced"]["userSvtGrand"] = [
        {
            "grandGraphId": 1,
            "userSvtId": 1,
            "appendPassiveSkill": None,
            "script": script,
            "equipTarget2": {"svtId": None, "token": "synthetic-private"},
        }
    ]
    body, _ = export_statistics(sample)
    row = json.loads(body)["cache"]["replaced"]["userSvtGrand"][0]
    assert "appendPassiveSkill" not in row and "script" not in row
    assert row["equipTarget2"] == {} and b"synthetic-private" not in body


def test_nested_error_identifies_schema_path_without_value(sample):
    sample["cache"]["replaced"]["userSvtGrand"] = [
        {
            "grandGraphId": 1,
            "userSvtId": 1,
            "appendPassiveSkill": [{"skillId": "synthetic-private-value", "skillLv": 1}],
        }
    ]
    with pytest.raises(ExportError) as caught:
        export_statistics(sample)
    assert caught.value.code == "STAT_FIELD_USERSVTGRAND_APPENDPASSIVESKILL_SKILLID"
    assert "synthetic-private-value" not in str(caught.value)


def test_field_error_codes_are_fixed_bounded_and_do_not_contain_values():
    from fgo_local_exporter.statistics import FIELD_ERROR_REASONS

    assert FIELD_ERROR_REASONS and all(len(code) <= 64 for code in FIELD_ERROR_REASONS)
    assert "STAT_FIELD_USERSVT_LV" in FIELD_ERROR_REASONS
    assert not any("synthetic" in value for value in FIELD_ERROR_REASONS.values())
