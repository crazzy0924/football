"""
Evaluation Framework v3.0

Lockbox evaluation: test on held-out future data only.
Multi-metric: Brier Score, Log Loss, accuracy, calibration.
Baseline comparison: must beat "always guess league average".

Preserved from v2.0 with minor import fixes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    """Single evaluation result."""
    n_matches: int = 0

    # Probability quality
    brier_score: float = 0.0
    log_loss: float = 0.0
    accuracy: float = 0.0

    # Calibration
    calibration: dict[str, Any] = field(default_factory=dict)

    # vs baseline
    baseline_brier: float = 0.0
    beats_baseline: bool = False
    improvement_vs_baseline: float = 0.0

    # Bias diagnostics
    home_bias: float = 0.0
    draw_bias: float = 0.0
    overconfidence: float = 0.0
    verdict: str = ""


def lockbox_evaluate(
    predictions: list[dict],
    league_stats: dict[str, dict] | None = None,
    league_code: str = "",
) -> EvalResult:
    """Lockbox evaluation — pure input→output, no parameter tuning.

    Args:
        predictions: list of dicts with home_win/draw/away_win and actual ("H"/"D"/"A")
        league_stats: optional dict of league_code → {home_win_rate, draw_rate, away_win_rate}
        league_code: fallback league code for baseline

    Returns:
        EvalResult with all metrics
    """
    if not predictions:
        return EvalResult(n_matches=0, verdict="No data to evaluate")

    n = len(predictions)
    brier_sum = 0.0
    logloss_sum = 0.0
    correct = 0
    home_bias_sum = 0.0
    draw_bias_sum = 0.0
    overconf_sum = 0.0

    buckets = defaultdict(lambda: {"count": 0, "actual": 0})

    for pred in predictions:
        ph = pred.get("home_win", 0.33)
        pd = pred.get("draw", 0.33)
        pa = pred.get("away_win", 0.33)
        actual = pred.get("actual", "?")

        if actual == "?":
            continue

        ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(
            actual, (0, 0, 0)
        )

        # Brier Score
        brier = (ph - ah) ** 2 + (pd - ad) ** 2 + (pa - aa) ** 2
        brier_sum += brier

        # Log Loss
        actual_prob = max({"H": ph, "D": pd, "A": pa}.get(actual, 0.01), 1e-10)
        logloss_sum += -math.log(actual_prob)

        # Direction accuracy
        pick = "H" if ph >= pd and ph >= pa else "A" if pa >= ph and pa >= pd else "D"
        if pick == actual:
            correct += 1

        # Bias tracking
        if actual == "H":
            home_bias_sum += ph - 1.0
        elif actual == "D":
            draw_bias_sum += 1.0 - pd
        overconf_sum += abs(ph - ah)

        # Calibration bucket
        bucket_key = int(ph * 10) / 10
        buckets[bucket_key]["count"] += 1
        buckets[bucket_key]["actual"] += ah

    result = EvalResult(
        n_matches=n,
        brier_score=round(brier_sum / n, 4),
        log_loss=round(logloss_sum / n, 4),
        accuracy=round(correct / n, 4),
        home_bias=round(home_bias_sum / n, 4),
        draw_bias=round(draw_bias_sum / n, 4),
        overconfidence=round(overconf_sum / n, 4),
    )

    # Baseline comparison
    if league_stats:
        ls = league_stats
        bl_h = ls.get("home_win_rate", 0.44)
        bl_d = ls.get("draw_rate", 0.26)
        bl_a = ls.get("away_win_rate", 0.30)
    else:
        # Default league-agnostic baseline
        bl_h, bl_d, bl_a = 0.44, 0.26, 0.30

    bl_brier = 0.0
    for pred in predictions:
        actual = pred.get("actual", "?")
        if actual == "?":
            continue
        ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(
            actual, (0, 0, 0)
        )
        bl_brier += (bl_h - ah) ** 2 + (bl_d - ad) ** 2 + (bl_a - aa) ** 2
    result.baseline_brier = round(bl_brier / n, 4)
    result.beats_baseline = result.brier_score < result.baseline_brier
    result.improvement_vs_baseline = round(result.baseline_brier - result.brier_score, 4)

    # Calibration quality
    calib = []
    for bk in sorted(buckets.keys()):
        b = buckets[bk]
        if b["count"] > 0:
            calib.append({
                "predicted_bucket": round(bk, 1),
                "count": b["count"],
                "actual_rate": round(b["actual"] / b["count"], 3),
            })
    result.calibration = {
        "buckets": calib,
        "quality": (
            "Good" if abs(result.home_bias) < 0.05 and result.overconfidence < 0.15
            else "Mild miscalibration" if abs(result.home_bias) < 0.10
            else "Severe miscalibration"
        ),
    }

    # Verdict
    issues = []
    if not result.beats_baseline:
        issues.append("Model does NOT beat league-mean baseline — DO NOT DEPLOY")
    if result.overconfidence > 0.20:
        issues.append(f"Overconfident (overestimation {result.overconfidence:.0%})")
    if abs(result.home_bias) > 0.08:
        direction = "overestimates" if result.home_bias > 0 else "underestimates"
        issues.append(f"Systematically {direction} home win probability ({result.home_bias:+.0%})")
    if result.log_loss > 1.10:
        issues.append("LogLoss > 1.10 indicates poor probability estimates")

    result.verdict = "PASS — ready to deploy" if not issues else "FAIL: " + "; ".join(issues)
    return result


def backtest_summary(results: list[EvalResult]) -> dict[str, Any]:
    """Aggregate multiple backtest fold results into a summary."""
    if not results:
        return {"error": "No results"}

    n_folds = len(results)
    avg_brier = sum(r.brier_score for r in results) / n_folds
    avg_logloss = sum(r.log_loss for r in results) / n_folds
    avg_accuracy = sum(r.accuracy for r in results) / n_folds
    all_beat = all(r.beats_baseline for r in results)

    return {
        "folds": n_folds,
        "avg_brier": round(avg_brier, 4),
        "avg_logloss": round(avg_logloss, 4),
        "avg_accuracy": round(avg_accuracy, 4),
        "all_folds_beat_baseline": all_beat,
        "per_fold": [
            {
                "brier": r.brier_score,
                "baseline_brier": r.baseline_brier,
                "beats": r.beats_baseline,
                "accuracy": r.accuracy,
                "n": r.n_matches,
            }
            for r in results
        ],
    }


def quick_eval(predictions: list[dict]) -> str:
    """Quick evaluation — returns one-line summary."""
    result = lockbox_evaluate(predictions)
    return (
        f"Brier={result.brier_score} LogLoss={result.log_loss} "
        f"Acc={result.accuracy:.0%} "
        f"{'BEATS' if result.beats_baseline else 'LOSES'} baseline "
        f"({result.improvement_vs_baseline:+.3f}) | {result.verdict}"
    )
