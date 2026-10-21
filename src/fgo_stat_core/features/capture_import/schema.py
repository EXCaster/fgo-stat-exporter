"""v1 明确白名单；字段不存在时保持缺失，不创建猜测的零值。"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["SCHEMA_VERSION", "TABLES", "FieldSpec", "TableSpec"]
SCHEMA_VERSION = "cn_capture.v1"
type Kind = Literal[
    "int",
    "signed",
    "ints",
    "signed_ints",
    "card_ref",
    "code_ref",
    "code_refs",
    "equip_ref",
    "optional_card_ref",
    "friend_code",
    "formation_name",
    "master_name",
]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Kind = "int"
    required: bool = False


@dataclass(frozen=True)
class TableSpec:
    key: str
    fields: tuple[FieldSpec, ...]


def _fields(names: str) -> tuple[FieldSpec, ...]:
    return tuple(FieldSpec(name) for name in names.split())


_CARD_FIELDS = (
    FieldSpec("id", "card_ref", True),
    FieldSpec("svtId", required=True),
    *_fields(
        "lv exp limitCount adjustHp adjustAtk skillLv1 skillLv2 skillLv3 "
        "treasureDeviceLv1 exceedCount hp atk isLock"
    ),
    FieldSpec("status", "signed"),
)

TABLES: dict[str, TableSpec] = {
    "userGame": TableSpec(
        "account_key",
        _fields(
            "lv exp qp costMax actMax actRecoverAt carryOverActPoint freeStone chargeStone stone"
        ),
    ),
    "userItem": TableSpec(
        "itemId",
        (
            FieldSpec("itemId", required=True),
            FieldSpec("num", required=True),
        ),
    ),
    "userSvt": TableSpec("id", _CARD_FIELDS),
    "userSvtStorage": TableSpec("id", _CARD_FIELDS),
    "userSvtCollection": TableSpec(
        "svtId",
        (
            FieldSpec("svtId", required=True),
            *_fields(
                "friendshipRank friendship friendshipExceedCount maxLv maxLimitCount "
                "skillLv1 skillLv2 skillLv3 treasureDeviceLv1 getNum totalGetNum"
            ),
            FieldSpec("costumeIds", "signed_ints"),
        ),
    ),
    "userSvtCoin": TableSpec(
        "svtId",
        (
            FieldSpec("svtId", required=True),
            FieldSpec("num", required=True),
        ),
    ),
    "userSvtAppendPassiveSkill": TableSpec(
        "svtId",
        (
            FieldSpec("svtId", required=True),
            FieldSpec("unlockNums", "ints", True),
        ),
    ),
    "userSvtAppendPassiveSkillLv": TableSpec(
        "userSvtId",
        (
            FieldSpec("userSvtId", "card_ref", True),
            FieldSpec("appendPassiveSkillNums", "ints", True),
            FieldSpec("appendPassiveSkillLvs", "ints", True),
        ),
    ),
    "userEquip": TableSpec(
        "id",
        (
            FieldSpec("id", "equip_ref", True),
            FieldSpec("equipId", required=True),
            *_fields("lv exp"),
        ),
    ),
    "userCommandCode": TableSpec(
        "id",
        (
            FieldSpec("id", "code_ref", True),
            FieldSpec("commandCodeId", required=True),
        ),
    ),
    "userSvtCommandCode": TableSpec(
        "svtId",
        (
            FieldSpec("svtId", required=True),
            FieldSpec("userCommandCodeIds", "code_refs", True),
        ),
    ),
    "userSvtCommandCard": TableSpec(
        "svtId",
        (
            FieldSpec("svtId", required=True),
            FieldSpec("commandCardParam", "ints", True),
        ),
    ),
    "userClassBoardSquare": TableSpec(
        "classBoardBaseId",
        (
            FieldSpec("classBoardBaseId", required=True),
            FieldSpec("classBoardSquareIds", "ints", True),
            FieldSpec("classBoardUnlockSquareIds", "ints", True),
        ),
    ),
}

# 报告显式选择 v2；v1 调用及存储范围保持原样。
REPORT_SCHEMA_VERSION = "cn_capture.v2"
REPORT_TABLES = dict(TABLES)
REPORT_TABLES.update(
    {
        "userGame": TableSpec(
            "account_key",
            TABLES["userGame"].fields
            + (
                FieldSpec("name", "master_name"),
                FieldSpec("createdAt"),
                FieldSpec("friendCode", "friend_code"),
                FieldSpec("fixMainSupportDeckIds", "ints"),
                FieldSpec("fixEventSupportDeckIds", "ints"),
                FieldSpec("mainSupportDeckId"),
                FieldSpec("eventSupportDeckId"),
                FieldSpec("pushUserSvtId", "optional_card_ref"),
                FieldSpec("favoriteUserSvtId", "optional_card_ref"),
            ),
        ),
        "userSvt": TableSpec("id", _CARD_FIELDS + _fields("createdAt dispLimitCount transformVal")),
        "userSvtStorage": TableSpec(
            "id", _CARD_FIELDS + _fields("createdAt dispLimitCount transformVal")
        ),
        "userSvtCollection": TableSpec(
            "svtId", TABLES["userSvtCollection"].fields + _fields("status")
        ),
        "userLogin": TableSpec("account_key", _fields("totalLoginCount seqLoginCount")),
        "userGacha": TableSpec(
            "gachaId", (FieldSpec("gachaId", required=True), FieldSpec("num", required=True))
        ),
        "userQuest": TableSpec(
            "questId",
            (FieldSpec("questId", required=True),)
            + _fields("questPhase clearNum challengeNum updatedAt"),
        ),
        "userShop": TableSpec(
            "shopId", (FieldSpec("shopId", required=True), FieldSpec("num", required=True))
        ),
        "userSupportDeck": TableSpec(
            "supportDeckId",
            (FieldSpec("supportDeckId", required=True), FieldSpec("name", "formation_name")),
        ),
        "userSvtLeader": TableSpec(
            "slot_key",
            (
                FieldSpec("supportDeckId", required=True),
                FieldSpec("classId", required=True),
                FieldSpec("userSvtId", "optional_card_ref", True),
                FieldSpec("svtId", required=True),
            )
            + _fields(
                "lv treasureDeviceLv skillLv1 skillLv2 skillLv3 ceSvtId ceLv ceLimitCount grandSvt "
                "hp atk adjustHp adjustAtk ceHp ceAtk skillId1 skillId2 skillId3 "
                "dispLimitCount exceedCount"
            )
            + (
                FieldSpec("ceUserSvtId", "optional_card_ref"),
                FieldSpec("appendSkillIds", "ints"),
                FieldSpec("appendSkillLvs", "ints"),
            ),
        ),
        "userSvtGrand": TableSpec(
            "grandGraphId",
            (
                FieldSpec("grandGraphId", required=True),
                FieldSpec("userSvtId", "card_ref", True),
                FieldSpec("equipTarget2SkillChange", "signed"),
            )
            + _fields(
                "svtId lv treasureDeviceLv skillLv1 skillLv2 skillLv3 grandSvt "
                "hp atk adjustHp adjustAtk skillId1 skillId2 skillId3 dispLimitCount exceedCount"
            )
            + tuple(
                field
                for prefix in ("ce", "ce2", "ce3")
                for field in (
                    FieldSpec(prefix + "SvtId"),
                    FieldSpec(prefix + "UserSvtId", "optional_card_ref"),
                    FieldSpec(prefix + "Lv"),
                    FieldSpec(prefix + "LimitCount"),
                    FieldSpec(prefix + "Hp"),
                    FieldSpec(prefix + "Atk"),
                )
            )
            + (FieldSpec("appendSkillIds", "ints"), FieldSpec("appendSkillLvs", "ints")),
        ),
    }
)
