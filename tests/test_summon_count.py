"""总抽数包含福袋，五星次数只扣除每条福袋记录的一次保底。"""

from fgo_stat_core.contracts.models import Snapshot
from fgo_stat_core.contracts.report_master import GachaMaster, ReportMasterData, ServantMaster
from fgo_stat_core.features.report.calculator import build_report


def test_total_pulls_include_lucky_bag_and_exclude_friend_points():
    master = ReportMasterData(
        "artificial",
        1792670000,
        servants={
            100100: ServantMaster(100100, "人工五星", 5, "saber", True, True, frozenset({"gacha"}))
        },
        gachas={
            1: GachaMaster(1, "人工友情池", 3, 1, 2, 0),
            1001: GachaMaster(1001, "人工石池", 1, 1, 2, 0),
            2001: GachaMaster(2001, "人工福袋", 7, 1, 2, 0),
        },
    )
    snapshot = Snapshot(
        "artificial",
        "CN",
        "artificial-account",
        1792670000,
        {
            "userSvtCollection": ({"svtId": 100100, "status": 2, "totalGetNum": 19},),
            "userGacha": (
                {"gachaId": 1, "num": 50},
                {"gachaId": 1001, "num": 123},
                {"gachaId": 2001, "num": 11},
            ),
        },
    )
    metric = build_report(snapshot, master, generated_at=1792670000).summon_estimate
    assert metric.value.adjusted_pulls == 134
    assert metric.value.adjusted_ssr_acquisitions == 18
    assert metric.value.lucky_bag_records == 1
    assert metric.rule_id == "cn-summon.v2"
