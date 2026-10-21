"""国服服务器参数与 Chaldea 配装公式；不猜缺项，不重算或重复加芙芙。"""

from typing import Literal

from fgo_stat_core.contracts.models import Value
from fgo_stat_core.contracts.report import Issue, Metric, SupportParameters, TableName

__all__ = ["support_parameters"]


def support_parameters(
    row: dict[str, Value],
    *,
    context: Literal["normal_support", "grand_configuration"],
    grand: bool | None,
    grand_class_verified: bool,
) -> Metric[SupportParameters]:
    issues: list[Issue] = []

    def number(key: str) -> int | None:
        value = row.get(key)
        if type(value) is not int or value < 0:
            issues.append("CAPTURE_FIELD_MISSING")
            return None
        return value

    servant_hp, servant_atk = number("hp"), number("atk")
    adjust_hp, adjust_atk = number("adjustHp"), number("adjustAtk")
    fou_hp = adjust_hp * 10 if adjust_hp is not None else None
    fou_atk = adjust_atk * 10 if adjust_atk is not None else None
    grand_bonus: Literal[0, 1000] | None = None
    if grand is None:
        issues.append("PARTIAL_SOURCE")
    elif not grand:
        grand_bonus = 0
    elif grand_class_verified:
        grand_bonus = 1000
    else:
        issues.append("MASTER_DATA_MISSING")

    def equipment(stat: str) -> int | None:
        prefixes: tuple[str, ...] = ("ce",)
        if context == "grand_configuration":
            if grand is None:
                return None
            if grand:
                prefixes = ("ce", "ce2", "ce3")
        total = 0
        for prefix in prefixes:
            sid = number(prefix + "SvtId")
            if sid is None:
                return None
            if sid == 0:  # 显式未装备不要求不存在的礼装参数。
                continue
            value = number(prefix + stat.capitalize())
            if value is None:
                return None
            total += value
        return total

    equipment_hp, equipment_atk = equipment("hp"), equipment("atk")

    def compute(
        servant: int | None, fou: int | None, equip: int | None
    ) -> tuple[int | None, int | None]:
        if servant is not None and fou is not None and fou > servant:
            issues.append("PARTIAL_SOURCE")
            return None, None
        base = servant - fou if servant is not None and fou is not None else None
        total = (
            servant + grand_bonus + equip
            if servant is not None and grand_bonus is not None and equip is not None
            else None
        )
        return base, total

    base_hp, hp = compute(servant_hp, fou_hp, equipment_hp)
    base_atk, atk = compute(servant_atk, fou_atk, equipment_atk)
    value = None
    if servant_hp is not None or servant_atk is not None:
        value = SupportParameters(
            context=context,
            servant_hp=servant_hp,
            servant_atk=servant_atk,
            base_hp=base_hp,
            base_atk=base_atk,
            fou_hp=fou_hp,
            fou_atk=fou_atk,
            grand_bonus=grand_bonus,
            equipment_hp=equipment_hp,
            equipment_atk=equipment_atk,
            hp=hp,
            atk=atk,
        )
    source: TableName = "userSvtGrand" if context == "grand_configuration" else "userSvtLeader"
    return Metric(
        state="unavailable" if value is None else "partial" if issues else "ready",
        value=value,
        issues=tuple(dict.fromkeys(issues)),
        source_tables=(source,),
        rule_id="chaldea24.parameters." + context,
    )
