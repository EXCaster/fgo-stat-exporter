"""HP/ATK 用人工数值验证分量、场景、缺项与版本白名单。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from fgo_stat_core.contracts.models import CaptureError
from fgo_stat_core.contracts.report import SupportParameters
from fgo_stat_core.contracts.report_master import ReportMasterData, ServantMaster
from fgo_stat_core.features.capture_import.parser import parse_capture, snapshot_json
from fgo_stat_core.features.report.calculator import build_report
from fgo_stat_core.features.report.parameters import support_parameters


@pytest.fixture
def parameter_row():
    return {
        "hp": 12000,
        "atk": 9000,
        "adjustHp": 100,
        "adjustAtk": 200,
        "ceSvtId": 9100,
        "ceHp": 500,
        "ceAtk": 1000,
        "ce2SvtId": 9200,
        "ce2Hp": 100,
        "ce2Atk": 100,
        "ce3SvtId": 9300,
        "ce3Hp": 750,
        "ce3Atk": 0,
    }


def calculate(row, grand=False, context="normal_support", verified=True):
    return support_parameters(row, context=context, grand=grand, grand_class_verified=verified)


def test_server_value_already_includes_fou(parameter_row):
    metric = calculate(parameter_row)
    p = metric.value
    assert metric.state == "ready"
    assert (p.servant_hp, p.servant_atk) == (12000, 9000)
    assert (p.fou_hp, p.fou_atk) == (1000, 2000)
    assert (p.base_hp, p.base_atk) == (11000, 7000)
    assert (p.hp, p.atk) == (12500, 10000)  # 不能二次加芙芙。
    assert p.scope == "pre_battle_without_skill_effects"


def test_grand_bonus_applies_outside_special_quest_but_extra_ces_do_not(parameter_row):
    normal = calculate(parameter_row, grand=True).value
    special = calculate(parameter_row, grand=True, context="grand_configuration").value
    assert normal.grand_bonus == special.grand_bonus == 1000
    assert (normal.equipment_hp, normal.equipment_atk) == (500, 1000)
    assert (normal.hp, normal.atk) == (13500, 11000)
    assert (special.equipment_hp, special.equipment_atk) == (1350, 1100)
    assert (special.hp, special.atk) == (14350, 11100)


def test_non_grand_does_not_receive_extra_equipment_bonus(parameter_row):
    p = calculate(parameter_row, context="grand_configuration").value
    assert (p.grand_bonus, p.equipment_hp, p.hp) == (0, 500, 12500)


def test_grails_affect_level_values_not_an_extra_fixed_bonus(parameter_row):
    a = calculate(parameter_row).value
    parameter_row.update(lv=120, exceedCount=30, limitCount=4, hp=16000, atk=13000)
    b = calculate(parameter_row).value
    assert (b.hp - a.hp, b.atk - a.atk) == (4000, 4000)
    parameter_row.update(exceedCount=99, limitCount=99)
    assert calculate(parameter_row).value == b


def test_zero_fou_and_empty_ce_are_real_zero(parameter_row):
    parameter_row.update(adjustHp=0, adjustAtk=0, ceSvtId=0)
    parameter_row.pop("ceHp")
    parameter_row.pop("ceAtk")
    p = calculate(parameter_row)
    assert p.state == "ready" and p.value.fou_hp == 0
    assert p.value.base_hp == p.value.hp == 12000
    assert p.value.equipment_hp == p.value.equipment_atk == 0


@pytest.mark.parametrize(
    "missing", ["hp", "atk", "adjustHp", "adjustAtk", "ceHp", "ceAtk", "ceSvtId"]
)
def test_missing_field_kept_unknown_not_zero(parameter_row, missing):
    parameter_row.pop(missing)
    m = calculate(parameter_row)
    assert m.state == "partial" and "CAPTURE_FIELD_MISSING" in m.issues
    if missing in {"hp", "ceHp", "ceSvtId"}:
        assert m.value.hp is None
    if missing in {"atk", "ceAtk", "ceSvtId"}:
        assert m.value.atk is None
    if missing == "adjustHp":
        assert m.value.base_hp is None and m.value.fou_hp is None
        assert m.value.hp == 12500  # 原始值仍已含芙芙，组件缺项不损坏已知合计。


def test_missing_both_server_values_unavailable(parameter_row):
    parameter_row.pop("hp")
    parameter_row.pop("atk")
    assert calculate(parameter_row).state == "unavailable"
    assert calculate(parameter_row).value is None


@pytest.mark.parametrize("prefix", ["ce2", "ce3"])
def test_grand_missing_extra_ce_keeps_total_unknown(parameter_row, prefix):
    parameter_row.pop(prefix + "SvtId")
    p = calculate(parameter_row, grand=True, context="grand_configuration")
    assert p.state == "partial" and p.value.hp is None and p.value.atk is None
    assert calculate(parameter_row, grand=True).state == "ready"


def test_unknown_crown_flag_is_not_no_crown(parameter_row):
    p = calculate(parameter_row, grand=None)
    assert p.state == "partial" and "PARTIAL_SOURCE" in p.issues
    assert p.value.grand_bonus is None and p.value.hp is None


def test_crown_class_mapping_required(parameter_row):
    p = calculate(parameter_row, grand=True, verified=False)
    assert p.state == "partial" and "MASTER_DATA_MISSING" in p.issues
    assert p.value.grand_bonus is None and p.value.hp is None
    assert calculate(parameter_row, grand=False, verified=False).state == "ready"


def test_inconsistent_fou_does_not_clamp_or_emit_bad_total(parameter_row):
    parameter_row["adjustHp"] = 1300
    p = calculate(parameter_row)
    assert p.state == "partial" and "PARTIAL_SOURCE" in p.issues
    assert p.value.base_hp is None and p.value.hp is None
    assert p.value.atk == 10000


@pytest.mark.parametrize(
    "patch",
    [
        {"hp": 1},
        {"base_hp": 1},
        {"grand_bonus": 500},
        {"fou_hp": -1},
        {"atk": True},
        {"context": "battle_damage"},
        {"secret": "SYNTHETIC"},
    ],
)
def test_contract_rejects_invalid_or_inconsistent_parameters(parameter_row, patch):
    data = calculate(parameter_row).value.model_dump()
    data.update(patch)
    with pytest.raises(ValidationError):
        SupportParameters.model_validate(data)


def raw_capture(minimal):
    root = deepcopy(minimal)
    tables = root["cache"]["replaced"]
    tables["userGame"][0].update(fixMainSupportDeckIds=[1], fixEventSupportDeckIds=[])
    row = {
        "supportDeckId": 1,
        "classId": 0,
        "userSvtId": 901,
        "svtId": 101,
        "lv": 100,
        "treasureDeviceLv": 5,
        "skillLv1": 10,
        "skillLv2": 10,
        "skillLv3": 10,
        "grandSvt": 1,
        "appendPassiveSkill": [],
        "hp": 12000,
        "atk": 9000,
        "adjustHp": 100,
        "adjustAtk": 200,
        "equipTarget1": {
            "svtId": 9100,
            "userSvtId": 902,
            "lv": 30,
            "limitCount": 4,
            "hp": 500,
            "atk": 1000,
            "session": "SYNTHETIC_STAT_SECRET",
        },
    }
    tables["userSvtLeader"] = [row]
    tables["userSvtGrand"] = [
        dict(
            row,
            grandGraphId=10001,
            equipTarget2={"svtId": 0, "userSvtId": 0},
            equipTarget3={"svtId": 0, "userSvtId": 0},
        )
    ]
    return root


def test_whitelist_and_calculator_wiring(minimal_capture, encode_capture, hmac_key):
    root = raw_capture(minimal_capture)
    s = parse_capture(encode_capture(root), hmac_key, report_fields=True)
    master = ReportMasterData(
        "synthetic",
        1900000000,
        servants={101: ServantMaster(101, "演示", 5, "saber", True, True, frozenset(), 1)},
        grand_class_ids={1: 10001},
    )
    r = build_report(s, master, generated_at=1900000001, show_support=True)
    slot = r.supports.value[0].slots[0]
    grand = r.grand_supports.value[0].servant
    assert slot.parameters.value.hp == grand.parameters.value.hp == 13500
    assert slot.parameters.value.context == "normal_support"
    assert grand.parameters.value.context == "grand_configuration"
    assert slot.craft_essence.hp == 500 and slot.craft_essence.atk == 1000
    assert r.grand_supports.value[0].craft_essences[0].craft_essence.hp == 500
    assert "SYNTHETIC_STAT_SECRET" not in snapshot_json(s) + r.model_dump_json()
    assert "userSvtLeader" not in parse_capture(encode_capture(root), hmac_key).tables


@pytest.mark.parametrize("prefix,position", [("ce", 1), ("ce2", 2), ("ce3", 3)])
def test_flat_stats_cannot_spoof_missing_equipment(
    minimal_capture, encode_capture, hmac_key, prefix, position
):
    root = raw_capture(minimal_capture)
    row = root["cache"]["replaced"]["userSvtGrand"][0]
    row.pop(f"equipTarget{position}")
    row.update({prefix + "Hp": 999, prefix + "Atk": 999})
    s = parse_capture(encode_capture(root), hmac_key, report_fields=True)
    assert prefix + "Hp" not in s.tables["userSvtGrand"][0]
    assert prefix + "Atk" not in s.tables["userSvtGrand"][0]


@pytest.mark.parametrize(
    "path", ["hp", "atk", "adjustHp", "adjustAtk", "equipTarget1.hp", "equipTarget1.atk"]
)
@pytest.mark.parametrize("bad", [-1, True, "NaN", [1]])
def test_invalid_numeric_fields_rejected(minimal_capture, encode_capture, hmac_key, path, bad):
    root = raw_capture(minimal_capture)
    row = root["cache"]["replaced"]["userSvtLeader"][0]
    if "." in path:
        parent, field = path.split(".")
        row[parent][field] = bad
    else:
        row[path] = bad
    with pytest.raises(CaptureError):
        parse_capture(encode_capture(root), hmac_key, report_fields=True)


def test_append_wiring_and_public_asset_plan(minimal_capture, encode_capture, hmac_key):
    from dataclasses import replace

    from fgo_stat_core.contracts.report_master import SkillMaster
    from fgo_stat_core.infrastructure.report_assets import _plan

    root = raw_capture(minimal_capture)
    for table in ("userSvtLeader", "userSvtGrand"):
        root["cache"]["replaced"][table][0]["appendPassiveSkill"] = [
            {"skillId": 302, "skillLv": 10}
        ]
    s = parse_capture(encode_capture(root), hmac_key, report_fields=True)
    servant = ServantMaster(101, "演示", 5, "saber", True, True, frozenset(), 1)
    master = ReportMasterData(
        "synthetic",
        1900000000,
        servants={101: replace(servant, append_skill_ids={100 + i: 301 + i for i in range(5)})},
        skills={i: SkillMaster(i, "演示追加", True) for i in range(301, 306)},
        grand_class_ids={1: 10001},
        class_icon_ids={1: 1, 10001: 10001},
    )
    r = build_report(s, master, generated_at=1900000001, show_support=True)
    slot = r.supports.value[0].slots[0]
    grand = r.grand_supports.value[0].servant
    assert slot.append_skills.state == grand.append_skills.state == "ready"
    assert slot.append_skills.value[1].level == grand.append_skills.value[1].level == 10
    assert (
        slot.class_icon_key == "class-3-1.png" and slot.grand_class_icon_key == "class-3-10001.png"
    )
    assert slot.active_skills is None and slot.passive_skills is None
    skills = {
        i: {"icon": f"https://static.atlasacademy.io/JP/SkillIcons/skill_{i}.png"}
        for i in range(301, 306)
    }
    jobs = _plan(r, {}, {}, {}, skills)
    names = {v.filename for v in jobs}
    assert {f"skill-{i}.png" for i in range(301, 306)} <= names
    assert {"class-3-1.png", "class-3-10001.png"} <= names
    assert all("?" not in v.url for v in jobs)
