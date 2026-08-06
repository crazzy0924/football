"""
Dixon-Coles (1997) ρ 修正

问题: 标准泊松模型系统性低估 0-0, 1-0, 0-1, 1-1 四个低比分
原因: 两个独立的泊松分布假设球队进球互不影响, 但实际比赛中
      0-0和1-1的频率显著高于泊松预测

解: τ(gh,ga) 修正因子, 引入 ρ 参数捕捉低比分的依赖结构

公式:
  P(gh,ga) = τ(gh,ga) × Poisson(gh|λh) × Poisson(ga|λa)

  τ(0,0) = 1 - λh·λa·ρ   |  τ(1,0) = 1 + λh·ρ
  τ(0,1) = 1 + λa·ρ       |  τ(1,1) = 1 - ρ
  τ(其他) = 1

ρ 范围: -0.15 ~ 0.05 (通常负值, 越大修正越强)

参考文献: Dixon & Coles (1997) "Modelling Association Football Scores"
"""
from __future__ import annotations

import math
from typing import Any


# ============================================================
# 核心: Dixon-Coles 修正
# ============================================================

def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def tau(gh: int, ga: int, lam_h: float, lam_a: float, rho: float) -> float:
    """Dixon-Coles τ 修正因子

    Args:
        gh: 主队进球
        ga: 客队进球
        lam_h: 主队 λ
        lam_a: 客队 λ
        rho:   ρ 参数 (典型值 -0.10)

    Returns:
        修正乘数 (通常 0.9~1.1)
    """
    if gh == 0 and ga == 0:
        return max(0.0, 1.0 - lam_h * lam_a * rho)
    elif gh == 1 and ga == 0:
        return max(0.0, 1.0 + lam_h * rho)
    elif gh == 0 and ga == 1:
        return max(0.0, 1.0 + lam_a * rho)
    elif gh == 1 and ga == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def dc_score_probability(gh: int, ga: int, lam_h: float, lam_a: float,
                         rho: float = -0.10) -> float:
    """Dixon-Coles 修正后的比分概率

    P(gh,ga) = τ(gh,ga) × Poisson(gh|λh) × Poisson(ga|λa)
    """
    raw_p = poisson_pmf(gh, lam_h) * poisson_pmf(ga, lam_a)
    return raw_p * tau(gh, ga, lam_h, lam_a, rho)


def dc_score_matrix(lam_h: float, lam_a: float, max_g: int = 8,
                    rho: float = -0.10) -> dict[str, float]:
    """生成 Dixon-Coles 修正后的完整比分矩阵

    Returns:
        {"0-0": 0.08, "1-0": 0.12, "1-1": 0.10, ...}
    """
    dist: dict[str, float] = {}
    total = 0.0

    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = dc_score_probability(h, a, lam_h, lam_a, rho)
            dist[f"{h}-{a}"] = p
            total += p

    # 归一化
    for k in dist:
        dist[k] /= total

    return dist


def dc_marginals(lam_h: float, lam_a: float, max_g: int = 8,
                 rho: float = -0.10) -> dict[str, Any]:
    """Dixon-Coles 修正后的胜平负 + 大小球 + BTTS

    这是替代标准泊松的直接入口函数。

    Returns:
        {
            "home_win": 0.45, "draw": 0.28, "away_win": 0.27,
            "over_25": 0.52, "btts": 0.55,
            "top_scores": [("2-1", 0.12), ...],
            "concentration": 0.06,
            "diagnostics": {"1-1_prob": 0.08, "0-0_prob": 0.06, ...}
        }
    """
    dist = dc_score_matrix(lam_h, lam_a, max_g, rho)

    hw = dr = aw = 0.0
    over25 = over35 = btts = 0.0
    scores_list = []

    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a: hw += prob
        elif h == a: dr += prob
        else: aw += prob
        if h + a > 2.5: over25 += prob
        if h + a > 3.5: over35 += prob
        if h > 0 and a > 0: btts += prob
        scores_list.append((score, prob))

    scores_list.sort(key=lambda x: x[1], reverse=True)
    conc = sum(p * p for _, p in scores_list)

    return {
        "score_distribution": dict(scores_list),
        "home_win": round(hw, 4),
        "draw": round(dr, 4),
        "away_win": round(aw, 4),
        "over_25": round(over25, 4),
        "over_35": round(over35, 4),
        "btts": round(btts, 4),
        "top_5_scores": scores_list[:5],
        "concentration": round(conc, 4),
        "diagnostics": {
            "1-1_prob": round(dist.get("1-1", 0), 4),
            "0-0_prob": round(dist.get("0-0", 0), 4),
            "1-0_prob": round(dist.get("1-0", 0), 4),
            "0-1_prob": round(dist.get("0-1", 0), 4),
        },
        "rho": rho,
    }


# ============================================================
# ρ 参数校准
# ============================================================

def estimate_rho(actual_scores: list[tuple[int, int]],
                 lam_h_list: list[float], lam_a_list: list[float]) -> float:
    """从历史数据用最大似然估计 ρ

    Args:
        actual_scores: [(主队进球, 客队进球), ...]
        lam_h_list:     每场主队 λ
        lam_a_list:     每场客队 λ

    Returns:
        最优 ρ 值
    """
    # 网格搜索: ρ ∈ [-0.15, 0.05]
    best_rho = -0.10
    best_ll = float('-inf')

    for rho in [x/100 for x in range(-15, 6, 1)]:
        ll = 0.0
        for (gh, ga), lh, la in zip(actual_scores, lam_h_list, lam_a_list):
            p = dc_score_probability(gh, ga, lh, la, rho)
            ll += math.log(max(p, 1e-10))
        if ll > best_ll:
            best_ll = ll
            best_rho = rho

    return round(best_rho, 4)
