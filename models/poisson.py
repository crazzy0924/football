"""
Poisson Distribution Utilities

Pure math — no dependencies beyond stdlib math.
Extracted from dixon_coles.py for clean separation.
"""
from __future__ import annotations

import math


def poisson_pmf(k: float, lam: float) -> float:
    """Poisson probability mass function: P(X = k) for rate λ.

    k 允许小数 (2026-09-14): 用 xG 这类"期望进球"当拟合目标时, 计数不是整数。
    math.factorial 只吃整数, 会直接抛 TypeError (实测: 'float' object cannot be
    interpreted as an integer), 让整个 xG 实验在暖启动阶段就崩掉。
    换成 math.gamma(k + 1): 整数下与阶乘完全一致 (gamma(n+1) = n!), 小数下是它的
    连续延拓 —— 正是准泊松拟合需要的。原整数路径行为不变, 无回归风险。
    """
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.gamma(k + 1)


def score_matrix(lam_h: float, lam_a: float, max_g: int = 8) -> dict[str, float]:
    """Generate full score probability matrix from two independent Poissons.

    P(gh, ga) = Poisson(gh | λh) × Poisson(ga | λa)
    """
    dist: dict[str, float] = {}
    total = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_a)
            dist[f"{h}-{a}"] = p
            total += p

    # Normalize (truncation at max_g loses some probability mass)
    if total > 0:
        for k in dist:
            dist[k] /= total

    return dist


def marginals(lam_h: float, lam_a: float, max_g: int = 8) -> dict:
    """Compute H/D/A, over/under, BTTS from a Poisson score matrix."""
    dist = score_matrix(lam_h, lam_a, max_g)

    hw = dr = aw = 0.0
    over25 = over35 = btts = 0.0
    scores = []

    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a:
            hw += prob
        elif h == a:
            dr += prob
        else:
            aw += prob
        if h + a > 2.5:
            over25 += prob
        if h + a > 3.5:
            over35 += prob
        if h > 0 and a > 0:
            btts += prob
        scores.append((score, prob))

    scores.sort(key=lambda x: x[1], reverse=True)

    return {
        "score_distribution": dict(scores),
        "home_win": round(hw, 4),
        "draw": round(dr, 4),
        "away_win": round(aw, 4),
        "over_25": round(over25, 4),
        "over_35": round(over35, 4),
        "btts": round(btts, 4),
        "top_5_scores": scores[:5],
        "concentration": round(sum(p * p for _, p in scores), 4),
    }
