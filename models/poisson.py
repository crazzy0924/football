"""
Poisson Distribution Utilities

Pure math — no dependencies beyond stdlib math.
Extracted from dixon_coles.py for clean separation.
"""
from __future__ import annotations

import math


def poisson_pmf(k: int, lam: float) -> float:
    """Poisson probability mass function: P(X = k) for rate λ."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


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
