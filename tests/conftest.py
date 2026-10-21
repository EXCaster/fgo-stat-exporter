"""完全人工构造的国服登录响应，不读取外部文件或真实账号。"""

import json
from collections.abc import Callable
from typing import Any

import pytest


@pytest.fixture
def hmac_key() -> bytes:
    return b"SYNTHETIC-TEST-HMAC-KEY-ONLY-000000"


@pytest.fixture
def encode_capture() -> Callable[[dict[str, Any]], bytes]:
    def encode(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()

    return encode


@pytest.fixture
def minimal_capture() -> dict[str, Any]:
    return {
        "response": [{"nid": "login", "resCode": "00", "success": {}}],
        "cache": {
            "serverTime": 1_800_000_000,
            "replaced": {
                "userGame": [
                    {
                        "userId": "910000000001",
                        "friendCode": "000000000000001",
                        "rkchannel": "1",
                        "lv": "150",
                        "qp": "12345",
                    }
                ],
                "userItem": [{"itemId": "65001", "num": "17"}],
            },
        },
    }


@pytest.fixture
def synthetic_capture(minimal_capture: dict[str, Any]) -> dict[str, Any]:
    """实例与素材编号均为任意新造数字；标记字符串仅用于泄漏拒绝测试。"""
    root = minimal_capture
    account = "910000000001"
    replaced = root["cache"]["replaced"]
    replaced["userGame"][0].update(
        {
            "exp": 123456,
            "freeStone": 12,
            "chargeStone": 3,
            "usk": "SYNTHETIC_ONLY_USK_DO_NOT_PERSIST",
            "name": "SYNTHETIC_ONLY_DISPLAY_NAME",
            "unknownProfileField": {"token": "SYNTHETIC_ONLY_NESTED_TOKEN"},
        }
    )
    replaced["userItem"].append({"itemId": 65002, "num": 0, "userId": account})
    replaced.update(
        {
            "userSvt": [
                {
                    "id": "710000000101",
                    "svtId": 501001,
                    "lv": "80",
                    "status": -1,
                    "skillLv1": 10,
                    "userId": account,
                    "unknownCardField": "SYNTHETIC_ONLY_CARD",
                },
                {"id": "710000000102", "svtId": 501001, "lv": 1, "userId": account},
            ],
            "userSvtStorage": [{"id": "710000000103", "svtId": 501002, "lv": 40}],
            "userSvtCollection": [
                {"svtId": 501001, "friendshipRank": 5, "costumeIds": [101, "102", -103, "-104"]}
            ],
            "userSvtCoin": [{"svtId": "501001", "num": 120}],
            "userSvtAppendPassiveSkill": [{"svtId": 501001, "unlockNums": [100, "101"]}],
            "userSvtAppendPassiveSkillLv": [
                {
                    "userSvtId": "710000000101",
                    "appendPassiveSkillNums": [100, "101"],
                    "appendPassiveSkillLvs": [10, "1"],
                },
                {
                    "userSvtId": "710000000103",
                    "appendPassiveSkillNums": [100],
                    "appendPassiveSkillLvs": [3],
                },
            ],
            "userEquip": [{"id": "610000000101", "equipId": 95001, "lv": 10, "exp": "1234"}],
            "userCommandCode": [{"id": "810000000101", "commandCodeId": 97001}],
            "userSvtCommandCode": [
                {"svtId": 501001, "userCommandCodeIds": ["810000000101", -1, 0, "1", 1]}
            ],
            "userSvtCommandCard": [{"svtId": 501001, "commandCardParam": [20, "40", 0]}],
            "userClassBoardSquare": [
                {
                    "classBoardBaseId": 96001,
                    "classBoardSquareIds": [1, "2"],
                    "classBoardUnlockSquareIds": [1],
                }
            ],
            "unknownCredentialTable": [{"token": "SYNTHETIC_ONLY_UNKNOWN_TABLE_TOKEN"}],
        }
    )
    root.update(
        {
            "usk": "SYNTHETIC_ONLY_ROOT_USK",
            "token": "SYNTHETIC_ONLY_ROOT_TOKEN",
            "signature": "SYNTHETIC_ONLY_SIGNATURE",
            "cookie": "SYNTHETIC_ONLY_AUTH_COOKIE",
            "downloadUrl": "https://example.invalid/capture?token=SYNTHETIC_ONLY_URL_TOKEN",
            "unknownRoot": {"value": "SYNTHETIC_ONLY_UNKNOWN_ROOT"},
        }
    )
    root["response"][0]["success"] = {"session": "SYNTHETIC_ONLY_SUCCESS_SESSION"}
    return root


@pytest.fixture
def capture_bytes(
    synthetic_capture: dict[str, Any], encode_capture: Callable[[dict[str, Any]], bytes]
) -> bytes:
    return encode_capture(synthetic_capture)
