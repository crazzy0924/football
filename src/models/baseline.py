"""
极简联赛均值基线模型

原则: 任何新增特征必须在此基线上有统计学显著的提升, 否则不保留。
这也是"锁箱测试"的参照基准——基线的每一行输出都可追溯到一个简单的乘法。

基线公式:
  P(主胜) = 联赛主场胜率
  P(平局) = 联赛平局率
  P(客胜) = 联赛客场胜率
  E[总进球] = 联赛场均总进球
  E[角球] = 联赛场均角球

基线不关心球队是谁——它代表了"闭着眼睛按联赛平均值猜"的预测。
如果你的模型连这个都打不过, 说明模型在学噪声。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.league_profiles import LeagueProfile, get_profile


@dataclass
class BaselinePrediction:
    """基线预测——完全基于联赛均值, 不涉及任何球队特定信息"""
    league: str
    home_team: str
    away_team: str

    # 胜平负 (纯联赛均值)
    home_win: float
    draw: float
    away_win: float

    # 进球
    expected_total_goals: float
    expected_home_goals: float
    expected_away_goals: float

    # 市场
    over_25: float
    btts: float

    # 角球
    expected_corners: float

    # 溯源
    source: str = "联赛历史均值, 不含球队特定信息"


def baseline_predict(
    home_team: str,
    away_team: str,
    league_code: str,
) -> BaselinePrediction:
    """生成基线预测

    这是最笨的预测——直接用联赛平均值, 不看球队是谁。
    用作所有高级模型的比较基准。
    """
    p = get_profile(league_code)

    return BaselinePrediction(
        league=p.name,
        home_team=home_team,
        away_team=away_team,
        home_win=round(p.home_win_rate, 4),
        draw=round(p.draw_rate, 4),
        away_win=round(p.away_win_rate, 4),
        expected_total_goals=round(p.avg_total_goals, 2),
        expected_home_goals=round(p.avg_home_goals, 2),
        expected_away_goals=round(p.avg_away_goals, 2),
        over_25=round(p.over_25_rate, 4),
        btts=round(p.btts_rate, 4),
        expected_corners=round(p.avg_corners, 1),
        source=f"{p.name} 历史均值 ({p.notes})",
    )


def compare_to_baseline(
    model_pred: dict[str, float],  # {"home_win": 0.55, "draw": 0.25, "away_win": 0.20}
    league_code: str,
) -> dict[str, Any]:
    """将模型预测与基线对比, 判断是否有增量价值

    Returns:
        {
            "model_better_than_baseline": True/False,
            "brier_model": 0.xx,
            "brier_baseline": 0.xx,
            "improvement": "+0.0x",
            "verdict": "模型显著优于基线" / "模型不优于基线, 建议回退"
        }
    """
    p = get_profile(league_code)
    baseline = {
        "home_win": p.home_win_rate,
        "draw": p.draw_rate,
        "away_win": p.away_win_rate,
    }

    # 简化的Brier比较 (需要实际赛果才能完整计算)
    baseline_variance = (
        p.home_win_rate * (1 - p.home_win_rate) ** 2
        + p.draw_rate * (1 - p.draw_rate) ** 2
        + p.away_win_rate * (1 - p.away_win_rate) ** 2
    )

    return {
        "baseline_probs": baseline,
        "model_probs": model_pred,
        "baseline_benchmark_brier": round(baseline_variance, 4),
        "note": "完整Brier需实际赛果。此处为基线理论方差下限。",
        "rule": "若模型Brier > 此值 → 模型在学噪声, 应回退到基线",
    }
