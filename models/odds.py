"""
Odds Analysis Module v3.0

Simplified from v2.0 odds_analyzer.py.
- Shin de-vigging: strip bookmaker margin from odds
- Kelly criterion: optimal stake sizing
- Value detection: model vs market comparison

Removed: Betfair index (no data available), OddsComparison (over-engineered)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValueDetection:
    """Value betting signal."""
    home_value: float       # model - market (positive = edge)
    draw_value: float
    away_value: float
    best_direction: str     # "home" | "draw" | "away" | "none"
    kelly_fraction: float   # 0 = no bet, up to ~0.25
    confidence: str         # "high" | "medium" | "low" | "none"


# ============================================================
# Shin de-vigging
# ============================================================

def implied_probability(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    method: str = "proportional",
) -> dict:
    """Convert decimal odds to true probabilities by stripping margin.

    Args:
        method: "proportional" (default) or "shin" (more accurate)

    Returns:
        {"home": 0.48, "draw": 0.28, "away": 0.24, "margin": 0.036}
    """
    if odds_home <= 1.0 or odds_draw <= 1.0 or odds_away <= 1.0:
        return {"home": 0.33, "draw": 0.34, "away": 0.33, "margin": 0.05}

    inv = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    overround = sum(inv)

    if method == "shin":
        probs, margin = _shin_method(odds_home, odds_draw, odds_away)
        return {"home": round(probs[0], 4), "draw": round(probs[1], 4),
                "away": round(probs[2], 4), "margin": round(margin, 4)}

    # Proportional
    margin = overround - 1.0
    return {
        "home": round(inv[0] / overround, 4),
        "draw": round(inv[1] / overround, 4),
        "away": round(inv[2] / overround, 4),
        "margin": round(margin, 4),
    }


def _shin_method(o1: float, o2: float, o3: float) -> tuple[list[float], float]:
    """Shin (1993) method for margin stripping via bisection search."""
    lo, hi = 0.0, 0.5
    for _ in range(50):
        z = (lo + hi) / 2
        sum_term = 0.0
        for o in [o1, o2, o3]:
            t = (z * (1 - z)) / o + (1 - z) ** 2
            if t > 0:
                sum_term += t ** 0.5 - (1 - z)
        if sum_term > 1.0:
            hi = z
        else:
            lo = z

    z = (lo + hi) / 2
    probs = []
    for o in [o1, o2, o3]:
        t = (z * (1 - z)) / o + (1 - z) ** 2
        p = max(0.0, t ** 0.5 - (1 - z)) if t > 0 else 0.0
        probs.append(p)

    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]

    overround = sum(1.0 / o for o in [o1, o2, o3])
    return probs, overround - 1.0


# ============================================================
# Kelly Criterion
# ============================================================

def kelly_criterion(
    model_prob: float,
    decimal_odds: float,
    fraction: float = 0.25,  # 1/4 Kelly (conservative)
) -> float:
    """Kelly criterion: optimal fraction of bankroll to bet.

    f* = (b × p - q) / b

    Args:
        model_prob: model's estimated probability of winning
        decimal_odds: bookmaker's decimal odds
        fraction: multiplier (0.25 = quarter-Kelly)

    Returns:
        Recommended stake as fraction of bankroll (0 = no bet)
    """
    if decimal_odds <= 1.0 or model_prob <= 0:
        return 0.0

    b = decimal_odds - 1.0  # net odds
    q = 1.0 - model_prob
    full_kelly = (b * model_prob - q) / b
    return max(0.0, full_kelly * fraction)


# ============================================================
# Value Detection
# ============================================================

def detect_value(
    model_probs: list[float],    # [p_home, p_draw, p_away]
    market_odds: dict,           # {"home": 2.10, "draw": 3.50, "away": 3.80}
    kelly_frac: float = 0.25,
) -> ValueDetection:
    """Compare model probabilities to market odds for value detection.

    Args:
        model_probs: [ph, pd, pa] from Dixon-Coles
        market_odds: {"home": odds, "draw": odds, "away": odds}
        kelly_frac: Kelly fraction (0.25 = quarter-Kelly conservative)

    Returns:
        ValueDetection with edge magnitudes and stake recommendation
    """
    implied = implied_probability(
        market_odds["home"], market_odds["draw"], market_odds["away"]
    )

    hv = model_probs[0] - implied["home"]
    dv = model_probs[1] - implied["draw"]
    av = model_probs[2] - implied["away"]

    values = {"home": hv, "draw": dv, "away": av}
    best_dir = max(values, key=values.get)
    best_val = values[best_dir]

    # Kelly for best direction
    kelly = 0.0
    if best_val > 0 and best_dir in market_odds:
        kelly = kelly_criterion(
            model_probs[{"home": 0, "draw": 1, "away": 2}[best_dir]],
            market_odds[best_dir],
            kelly_frac,
        )

    # Confidence level
    if best_val > 0.05 and kelly > 0.03:
        conf = "high"
    elif best_val > 0.02:
        conf = "medium"
    elif best_val > -0.02:
        conf = "low"
    else:
        conf = "none"

    return ValueDetection(
        home_value=round(hv, 4),
        draw_value=round(dv, 4),
        away_value=round(av, 4),
        best_direction=best_dir if best_val > 0 else "none",
        kelly_fraction=round(kelly, 4),
        confidence=conf,
    )
