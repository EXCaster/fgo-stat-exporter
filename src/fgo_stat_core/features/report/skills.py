"""助战主动技能与固有被动；不把追加、活动或条件被动混入 classPassive。"""

from typing import Literal, cast

from fgo_stat_core.contracts.models import CaptureError, Value
from fgo_stat_core.contracts.report import (
    ActiveIcons,
    AppendSkills,
    Issue,
    Metric,
    SupportActiveIcon,
    SupportAppendSkill,
    SupportSkill,
    TableName,
)
from fgo_stat_core.contracts.report_master import ReportMasterData, ServantMaster

__all__ = [
    "active_skills",
    "passive_skills",
    "append_skills",
    "active_skill_icons",
    "class_icon_key",
    "frame_type_base",
]
type ActiveSkills = tuple[SupportSkill | None, SupportSkill | None, SupportSkill | None]


def frame_type_base(
    row: dict[str, Value], servant: ServantMaster | None, master: ReportMasterData | None
) -> Literal[0, 1, 2, 3, 4, 5, 6, 7] | None:
    """已投入圣杯的公开 frameType；不由等级反推圣杯数或 Great 升格。"""
    if servant is None or master is None:
        return None
    count = row.get("exceedCount")
    if type(count) is not int or count <= 0:
        # 无圣杯时框型派生尚待原生 Set 行为核实，不借职介图标色阶猜框型。
        return None
    value = master.grail_frame_types.get((servant.rarity, count))
    return cast(Literal[0, 1, 2, 3, 4, 5, 6, 7], value) if value in range(8) else None


def append_skills(
    row: dict[str, Value],
    source: TableName,
    master: ReportMasterData | None,
) -> Metric[AppendSkills]:
    servant = master.servants.get(cast(int, row.get("svtId"))) if master else None
    mapping = servant.append_skill_ids if servant else {}
    issues: list[Issue] = []
    raw_ids, raw_levels = row.get("appendSkillIds"), row.get("appendSkillLvs")
    known = isinstance(raw_ids, tuple) and isinstance(raw_levels, tuple)
    if not known:
        issues.append("CAPTURE_FIELD_MISSING")
    ids = cast(tuple[int, ...], raw_ids) if known else ()
    levels = cast(tuple[int, ...], raw_levels) if known else ()
    if len(ids) > 10 or len(ids) != len(levels):
        raise CaptureError("REPORT_INPUT_LIMIT")
    # 未知ID不能被当作不存在的已开放项；有冲突时也不宣称其他槽未开放。
    if len(set(ids)) != len(ids) or any(type(v) is not int or not 0 <= v <= 10 for v in levels):
        known = False
        issues.append("PARTIAL_SOURCE")
    if set(ids) - set(mapping.values()):
        known = False
        issues.append("MASTER_DATA_MISSING")
    if len(set(mapping.values())) != len(mapping):
        known = False
        issues.append("MASTER_DATA_MISSING")
    captured = dict(zip(ids, levels, strict=True))
    slots: list[SupportAppendSkill] = []
    for num in (100, 101, 102, 103, 104):
        sid = mapping.get(num)
        skill = master.skills.get(sid) if master and sid else None
        if sid is None or skill is None or not skill.name or not skill.icon_available:
            issues.append("MASTER_DATA_MISSING")
        lv = captured.get(sid, 0) if sid is not None and known else None
        slots.append(
            SupportAppendSkill(
                num=num,
                state="unavailable" if lv is None else "unlocked" if lv > 0 else "locked",
                skill_id=sid,
                name=skill.name if skill else None,
                icon_key=f"skill-{sid}.png" if skill and skill.icon_available else None,
                level=lv if lv is not None and lv > 0 else None,
            )
        )
    return Metric(
        state="partial" if issues else "ready",
        value=cast(AppendSkills, tuple(slots)),
        issues=tuple(dict.fromkeys(issues)),
        source_tables=(source,),
        rule_id="chaldea24.support_append_skills",
    )


def _skill(
    sid: int,
    kind: Literal["active", "class_passive"],
    level: int | None,
    master: ReportMasterData | None,
    issues: list[Issue],
) -> SupportSkill:
    skill = master.skills.get(sid) if master else None
    if skill is None or not skill.name or not skill.icon_available:
        issues.append("MASTER_DATA_MISSING")
    return SupportSkill(
        skill_id=sid,
        kind=kind,
        level=level,
        name=skill.name if skill else None,
        icon_key=f"skill-{sid}.png" if skill and skill.icon_available else None,
    )


def active_skills(
    row: dict[str, Value],
    source: TableName,
    master: ReportMasterData | None,
) -> Metric[ActiveSkills]:
    issues: list[Issue] = []
    skills: list[SupportSkill | None] = []
    for i in (1, 2, 3):
        sid, lv = row.get(f"skillId{i}"), row.get(f"skillLv{i}")
        if type(sid) is not int or sid <= 0 or type(lv) is not int or lv < 0:
            issues.append("CAPTURE_FIELD_MISSING")
            skills.append(None)
        else:
            skills.append(_skill(sid, "active", lv, master, issues))
    return Metric(
        state="partial" if issues else "ready",
        value=cast(ActiveSkills, tuple(skills)),
        issues=tuple(dict.fromkeys(issues)),
        source_tables=(source,),
        rule_id="chaldea24.support_active_skills",
    )


def passive_skills(
    row: dict[str, Value],
    source: TableName,
    master: ReportMasterData | None,
) -> Metric[tuple[SupportSkill, ...]]:
    servant = master.servants.get(cast(int, row.get("svtId"))) if master else None
    if servant is None or servant.passive_skill_ids is None:
        return Metric(
            state="needs_master_data",
            issues=("MASTER_DATA_MISSING",),
            source_tables=(source,),
            rule_id="chaldea24.support_class_passives",
        )
    ids = servant.passive_skill_ids
    if servant.passive_overrides:
        disp = row.get("dispLimitCount")
        if type(disp) is not int or disp < 0:
            return Metric(
                state="unavailable",
                issues=("CAPTURE_FIELD_MISSING",),
                source_tables=(source,),
                rule_id="chaldea24.support_class_passives",
            )
        # Servant.dispLimitCountToLimitCount，随后 getAscended 的已解析覆盖表。
        form = {0: 0, 1: 0, 2: 2, 3: 4, 4: 4}.get(disp, disp)
        ids = servant.passive_overrides.get(form, ids)
    if len(ids) > 64:
        raise CaptureError("REPORT_INPUT_LIMIT")
    issues: list[Issue] = []
    skills = tuple(_skill(sid, "class_passive", None, master, issues) for sid in ids)
    return Metric(
        state="partial" if issues else "ready",
        value=skills,
        issues=tuple(dict.fromkeys(issues)),
        source_tables=(source,),
        rule_id="chaldea24.support_class_passives",
    )


def class_icon_key(
    servant: ServantMaster | None,
    master: ReportMasterData | None,
    *,
    grand: bool = False,
) -> str | None:
    if servant is None or master is None or servant.class_id is None:
        return None
    cid = master.grand_class_ids.get(servant.class_id) if grand else servant.class_id
    icon = master.class_icon_ids.get(cid) if cid is not None else None
    if icon is None:
        return None
    rarity = 3 if grand else {0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 3}.get(servant.rarity)
    rarity = {1003: 2, 17: 3, 1006: 2}.get(icon, rarity)
    if cid in {13, 14, 15, 16, 18, 19}:
        icon, rarity = 12, 2
    return f"class-{rarity}-{icon}.png" if rarity is not None else None


def active_skill_icons(
    row: dict[str, Value],
    source: TableName,
    master: ReportMasterData | None,
) -> Metric[ActiveIcons]:
    servant = master.servants.get(cast(int, row.get("svtId"))) if master else None
    icons: list[SupportActiveIcon] = []
    issues: list[Issue] = []
    for position in (1, 2, 3):
        sid = row.get(f"skillId{position}")
        skill = master.skills.get(sid) if master and type(sid) is int and sid > 0 else None
        key: str | None = None
        origin: Literal["captured_id", "shared_static_icon", "unavailable"] = "unavailable"
        if skill and skill.icon_available:
            key, origin = f"skill-{sid}.png", "captured_id"
        elif sid in {None, 0} and master and servant:
            candidates = [master.skills.get(i) for i in servant.active_skill_ids.get(position, ())]
            signatures = {c.icon_signature for c in candidates if c and c.icon_available}
            if (
                candidates
                and all(c and c.icon_available for c in candidates)
                and len(signatures) == 1
                and None not in signatures
            ):
                key, origin = f"active-shared-{servant.id}-{position}.png", "shared_static_icon"
        if key is None:
            issues.append("MASTER_DATA_MISSING")
        icons.append(SupportActiveIcon(position=position, source=origin, icon_key=key))
    return Metric(
        state="partial" if issues else "ready",
        value=cast(ActiveIcons, tuple(icons)),
        issues=tuple(dict.fromkeys(issues)),
        source_tables=(source,),
        rule_id="report.shared_active_icon.v1",
    )
