"""
Draw Calibration — Per-League Post-Hoc Adjustment

Dixon-Coles models goals as independent Poisson processes, which systematically
underestimates draws. The τ correction only covers 0-0, 1-0, 0-1, 1-1.

This module provides a lightweight post-hoc calibration:
- Per-league draw propensity factor derived from training data
- Shrinkage toward 1.0 based on sample size (small leagues don't overfit)
- Applied multiplicatively to draw probability, then renormalize H/D/A

Design rationale:
- Keeps the core DC model pure (MLE fitting unchanged)
- Only touches the output layer — minimal risk of breaking other predictions
- League-level is the right granularity: draw rates vary by league culture,
  referee style, and competitive balance, NOT by individual teams
"""

from __future__ import annotations

from typing import Any


def fit_draw_calibration(
    matches: list[dict],
    dc_model: Any,
    shrinkage_k: float = 200.0,
    factor_clip: tuple[float, float] = (0.80, 1.35),
) -> dict[str, dict[str, float]]:
    """Fit per-league draw calibration factors.

    Computes actual vs predicted draw rates on the training data itself,
    then shrinks the ratio toward 1.0 based on sample size.

    Args:
        matches: training matches with 'league_code', 'result', 'home_goals', 'away_goals'
        dc_model: fitted DixonColesModel (already trained on `matches`)
        shrinkage_k: regularization — factor = 1 + (raw-1)*n/(n+k)
                     k=200 means a league with 200 matches gets 50% shrinkage
        factor_clip: (min, max) for raw draw factor before shrinkage

    Returns:
        {league_code: {'draw_factor': float, 'n_matches': int, 'actual_draw_rate': float,
                       'pred_draw_rate': float, 'raw_factor': float}}
    """
    from collections import defaultdict

    # Accumulate per-league actual draws and predicted draw probabilities
    league_data: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "n_draws": 0, "sum_pred_draw": 0.0
    })

    for m in matches:
        league = m.get("league_code", "")
        if not league:
            continue

        ld = league_data[league]
        ld["n"] += 1
        if m.get("result") == "D":
            ld["n_draws"] += 1

        # Predict using the same model (no form factors — we want pure DC baseline)
        pred = dc_model.predict(
            m["home_team"], m["away_team"], league,
            form_factors=None,  # pure DC, no form
        )
        ld["sum_pred_draw"] += pred["draw"]

    # Compute per-league factors with shrinkage
    calibration: dict[str, dict[str, float]] = {}

    for league, ld in sorted(league_data.items()):
        n = ld["n"]
        if n < 10:
            continue

        actual_draw_rate = ld["n_draws"] / n
        pred_draw_rate = ld["sum_pred_draw"] / n
        raw_factor = actual_draw_rate / max(pred_draw_rate, 0.15)

        # Clip raw factor
        lo, hi = factor_clip
        raw_clipped = max(lo, min(hi, raw_factor))

        # Shrink toward 1.0: factor = 1 + (raw-1)*n/(n+k)
        shrink = n / (n + shrinkage_k)
        calibrated_factor = 1.0 + (raw_clipped - 1.0) * shrink

        calibration[league] = {
            "draw_factor": round(calibrated_factor, 4),
            "n_matches": n,
            "actual_draw_rate": round(actual_draw_rate, 4),
            "pred_draw_rate": round(pred_draw_rate, 4),
            "raw_factor": round(raw_factor, 4),
        }

    return calibration


def apply_draw_calibration(
    probs: dict[str, float],
    league_code: str,
    calibration: dict[str, dict[str, float]],
) -> tuple[float, float, float]:
    """Apply draw calibration to H/D/A probabilities.

    cal_draw = draw * factor
    Then redistribute the delta proportionally from home_win and away_win.

    Args:
        probs: {'home_win': p_h, 'draw': p_d, 'away_win': p_a}
        league_code: league identifier
        calibration: output from fit_draw_calibration()

    Returns:
        (calibrated_home_win, calibrated_draw, calibrated_away_win) — sum to 1
    """
    p_h = probs["home_win"]
    p_d = probs["draw"]
    p_a = probs["away_win"]

    cal = calibration.get(league_code, {})
    factor = cal.get("draw_factor", 1.0)

    if factor == 1.0 or p_d <= 0 or p_d >= 1:
        return p_h, p_d, p_a

    # Apply factor to draw probability
    new_d = p_d * factor

    # Clamp to [0, 1]
    new_d = max(0.0, min(1.0, new_d))

    # Redistribute the delta proportionally from H and A
    delta = new_d - p_d

    if abs(delta) < 0.0001:
        return p_h, p_d, p_a

    non_draw = p_h + p_a
    if non_draw <= 0:
        return p_h, new_d, p_a

    # Proportional redistribution
    h_share = p_h / non_draw
    a_share = p_a / non_draw

    new_h = p_h - delta * h_share
    new_a = p_a - delta * a_share

    # Safety clamp
    new_h = max(0.0, min(1.0, new_h))
    new_a = max(0.0, min(1.0, new_a))

    # Final renormalization (handles edge cases from clamping)
    total = new_h + new_d + new_a
    if total > 0:
        new_h /= total
        new_d /= total
        new_a /= total

    return round(new_h, 4), round(new_d, 4), round(new_a, 4)


def save_calibration(calibration: dict, path: str) -> None:
    """Save draw calibration to JSON."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)


def load_calibration(path: str) -> dict[str, dict[str, float]]:
    """Load draw calibration from JSON."""
    import json, os
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
