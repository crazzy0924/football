"""
最佳投注推荐引擎

参考:
  Football_Model: 结果投注>60%概率触发, 道具投注(BTTS/O2.5)>65%触发
  sports-trading: Edge threshold 5%, HIGH>10%, MEDIUM 5-10%
  Goal-Prediction-Model: 6模型基准 + 置信度分级

核心函数:
  recommend_bets() — 输入模型预测+市场赔率, 输出过滤后的投注建议
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 阈值配置
# ============================================================

@dataclass
class BetThresholds:
    """投注阈值 (可调)"""
    # 结果投注 (胜平负/让球)
    min_result_prob: float = 0.60          # 模型概率>60%才推荐结果投注
    min_edge: float = 0.05                 # 模型vs市场 edge >5%才推荐
    high_edge: float = 0.10                # edge >10% = HIGH置信

    # 道具投注 (大小球/BTTS/角球)
    min_prop_prob: float = 0.65            # 模型概率>65%才推荐道具投注

    # H2H权重
    h2h_weight: float = 0.20               # 交锋记录占20%权重

    # 赛季衰减
    season_decay_base: float = 0.85         # 每往前一个赛季, 权重×0.85


# 全局默认阈值
THRESHOLDS = BetThresholds()


# ============================================================
# 赛季衰减权重 (from Football_Model)
# ============================================================

def season_weight(season_year: int, current_year: int = 2026) -> float:
    """赛季衰减: weight = 1 / (1 + (current - season))

    2026赛季: 1.0
    2025赛季: 0.5
    2024赛季: 0.33
    2023赛季: 0.25
    """
    return 1.0 / (1.0 + (current_year - season_year))


# ============================================================
# Edge 检测 (from sports-trading)
# ============================================================

def detect_edge(model_prob: float, market_implied_prob: float,
                threshold: float = 0.05) -> dict[str, Any]:
    """检测模型 vs 市场的价值偏差

    Args:
        model_prob:          模型预测概率 (0~1)
        market_implied_prob: 市场隐含概率 (Shin去水后, 0~1)
        threshold:           edge阈值 (默认5%)

    Returns:
        {
            "edge": +0.07,
            "has_value": True,
            "confidence": "HIGH",
            "recommendation": "bet"
        }
    """
    edge = model_prob - market_implied_prob

    if edge <= threshold:
        return {"edge": round(edge, 4), "has_value": False,
                "confidence": "NONE", "recommendation": "skip"}

    if edge > THRESHOLDS.high_edge:
        conf = "HIGH"
    elif edge > THRESHOLDS.min_edge:
        conf = "MEDIUM"
    else:
        conf = "LOW"

    return {"edge": round(edge, 4), "has_value": True,
            "confidence": conf, "recommendation": "bet"}


# ============================================================
# 综合投注推荐
# ============================================================

def recommend_bets(
    home_team: str,
    away_team: str,
    model_home: float,          # 模型主胜概率
    model_draw: float,           # 模型平局概率
    model_away: float,           # 模型客胜概率
    market_home: float,          # 市场隐含主胜概率 (Shin去水)
    market_draw: float,
    market_away: float,
    model_over25: float = 0.0,   # 模型大2.5概率
    market_over25: float = 0.0,  # 市场大2.5概率
    model_btts: float = 0.0,     # 模型BTTS概率
    market_btts: float = 0.0,    # 市场BTTS概率
    h2h_win_rate: float | None = None,  # 交锋胜率 (可选)
) -> dict[str, Any]:
    """自动推荐最佳投注

    规则:
      1. 结果投注: 模型概率>60% AND edge>5% → 推荐
      2. 道具投注: 模型概率>65% AND edge>5% → 推荐
      3. 同时满足时, 选edge更大的

    Returns:
        {
            "best_bet": {"market": "1X2", "pick": "主胜", "odds": 2.10, "confidence": "HIGH"},
            "recommended_bets": [...],
            "skip_reason": None (if has recommendations)
        }
    """
    recommendations = []

    # 1. 检查结果投注
    result_picks = [
        ("主胜", model_home, market_home),
        ("平局", model_draw, market_draw),
        ("客胜", model_away, market_away),
    ]

    for pick_name, model_p, market_p in result_picks:
        if model_p >= THRESHOLDS.min_result_prob:
            edge_info = detect_edge(model_p, market_p)
            if edge_info["has_value"]:
                recommendations.append({
                    "type": "result",
                    "market": "1X2",
                    "pick": pick_name,
                    "model_prob": round(model_p, 4),
                    "market_prob": round(market_p, 4),
                    "edge": edge_info["edge"],
                    "confidence": edge_info["confidence"],
                })

    # 2. 检查道具投注
    if model_over25 > 0:
        prop_picks = [
            ("大2.5球", model_over25, market_over25),
            ("BTTS是", model_btts, market_btts),
        ]
        for pick_name, model_p, market_p in prop_picks:
            if model_p >= THRESHOLDS.min_prop_prob and market_p > 0:
                edge_info = detect_edge(model_p, market_p)
                if edge_info["has_value"]:
                    recommendations.append({
                        "type": "prop",
                        "market": pick_name.split(" ")[0] if " " in pick_name else pick_name,
                        "pick": pick_name,
                        "model_prob": round(model_p, 4),
                        "market_prob": round(market_p, 4),
                        "edge": edge_info["edge"],
                        "confidence": edge_info["confidence"],
                    })

    # 3. 按edge排序, 取最优
    recommendations.sort(key=lambda x: x["edge"], reverse=True)

    # 4. 加入H2H修正
    if h2h_win_rate is not None:
        for rec in recommendations:
            if rec["type"] == "result":
                # H2H有利 → boost edge
                if (rec["pick"] == "主胜" and h2h_win_rate > 0.50) or \
                   (rec["pick"] == "客胜" and h2h_win_rate < 0.50):
                    rec["edge"] = round(rec["edge"] + 0.02, 4)
                    rec["note"] = f"H2H加成 (交锋胜率{h2h_win_rate:.0%})"

    if not recommendations:
        return {
            "match": f"{home_team} vs {away_team}",
            "best_bet": None,
            "recommended_bets": [],
            "verdict": "无符合阈值的投注 (所有edge<5%或模型概率不达标)",
        }

    return {
        "match": f"{home_team} vs {away_team}",
        "best_bet": recommendations[0],
        "recommended_bets": recommendations,
        "verdict": f"推荐 {len(recommendations)} 个投注, 最佳: {recommendations[0]['pick']} (edge={recommendations[0]['edge']:+.1%})",
    }
