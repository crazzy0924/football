"""
Backtester v3.0

Time-series cross-validation with expanding windows.
Respects temporal ordering — never trains on future data.

Hard gate: model must beat league-mean baseline before live deployment.

Betting simulation: Bayesian fusion + Kelly sizing.
Only bets when posterior edge > threshold.
"""
from __future__ import annotations

import json
import os
from typing import Any

from models.elo import EloSystem
from models.dixon_coles import DixonColesModel
from models.evaluation import EvalResult, lockbox_evaluate, backtest_summary
from pipeline.data_loader import compute_league_stats


# Betting strategy parameters
EDGE_THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15]
KELLY_FRACTION = 0.25  # quarter-Kelly (conservative)


def run_backtest(
    matches: list[dict],
    state_dir: str = "data/state",
    output_dir: str = "data/output",
    n_folds: int = 2,
) -> dict[str, Any]:
    """Run expanding-window backtest with multiple betting strategies.

    Tests different edge thresholds to find the optimal one.
    """
    os.makedirs(output_dir, exist_ok=True)

    seasons = sorted(set(m["season"] for m in matches))
    print(f"Seasons: {seasons}")
    print(f"Testing edge thresholds: {[f'{t:.0%}' for t in EDGE_THRESHOLDS]}")

    if len(seasons) < 3:
        return {"error": f"Need at least 3 seasons, got {len(seasons)}"}

    test_seasons = seasons[-n_folds:]
    fold_results = []
    all_fold_data = []

    for test_season in test_seasons:
        print(f"\n{'='*60}")
        print(f"Fold: Test on {test_season}")
        print(f"{'='*60}")

        train_seasons = [s for s in seasons if s < test_season]
        train_matches = [m for m in matches if m["season"] in train_seasons]
        test_matches = [m for m in matches if m["season"] == test_season]

        print(f"Train: {len(train_matches)} matches from {train_seasons}")
        print(f"Test:  {len(test_matches)} matches from {test_season}")

        if len(train_matches) < 100 or len(test_matches) < 50:
            continue

        # Train on historical data only
        elo = EloSystem()
        elo.initialize_from_matches(train_matches)

        dc = DixonColesModel()
        try:
            dc.fit_mle(train_matches)
        except Exception as e:
            print(f"  MLE failed ({e}), falling back to fit_simple")
            dc.fit_simple(train_matches)

        league_stats = compute_league_stats(train_matches)

        # ── Recent form: chronological processing within test season ──
        # We maintain a pool of completed matches (training + already-seen test)
        # and recompute form factors before each test match.
        # This ensures form only uses data available BEFORE the match.
        from models.form_factor import compute_form_factors
        completed_matches = list(train_matches)  # start with all training data (prev seasons)

        # Sort test matches chronologically (they should already be sorted, but ensure)
        test_matches_sorted = sorted(test_matches, key=lambda m: (
            m.get("date", ""), m.get("kickoff", ""), m.get("commence_time", "")
        ))

        # Predict all test matches
        predictions = []
        bet_candidates = []

        # Track how many times we recompute form (every 50 matches for efficiency)
        form_cache = None
        form_cache_matches = -1
        form_recompute_interval = 50  # recompute after every N new matches

        for idx, m in enumerate(test_matches_sorted):
            # Recompute form factors periodically or if cache is stale
            if idx == 0 or len(completed_matches) - form_cache_matches >= form_recompute_interval:
                form_factors = compute_form_factors(
                    completed_matches,
                    dc.team_attack,
                    dc.team_defense,
                    dc.league_avg_goals,
                    dc.league_home_adv,
                )
                form_cache = form_factors
                form_cache_matches = len(completed_matches)

            pred = dc.predict(
                m["home_team"], m["away_team"], m["league_code"],
                form_factors=form_cache,
            )
            actual = m["result"]
            market_odds = m.get("odds", {})
            best_odds = _get_best_odds(market_odds)

            # Bayesian fusion with market odds
            if best_odds:
                bayes_result = _bayesian_fuse(pred, best_odds)
            else:
                bayes_result = None

            predictions.append({
                "home_win": pred["home_win"],
                "draw": pred["draw"],
                "away_win": pred["away_win"],
                "actual": actual,
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "league_code": m["league_code"],
            })

            if best_odds and bayes_result:
                bet_candidates.append({
                    "home_team": m["home_team"],
                    "away_team": m["away_team"],
                    "actual": actual,
                    "best_odds": best_odds,
                    "model_probs": [pred["home_win"], pred["draw"], pred["away_win"]],
                    "posterior": bayes_result["posterior"],
                    "raw_edge": bayes_result["raw_edges"],
                })

            # Feed actual result back into form pool (chronological — only past matches used)
            completed_matches.append({
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "league_code": m["league_code"],
                "home_goals": m["home_goals"],
                "away_goals": m["away_goals"],
            })

        # Evaluate Brier
        combined_ls = {
            "home_win_rate": sum(s.get("home_win_rate", 0.44) for s in league_stats.values()) / max(len(league_stats), 1),
            "draw_rate": sum(s.get("draw_rate", 0.26) for s in league_stats.values()) / max(len(league_stats), 1),
            "away_win_rate": sum(s.get("away_win_rate", 0.30) for s in league_stats.values()) / max(len(league_stats), 1),
        }
        eval_result = lockbox_evaluate(predictions, combined_ls)
        print(f"  Brier: {eval_result.brier_score} (baseline: {eval_result.baseline_brier})")
        print(f"  Accuracy: {eval_result.accuracy:.1%}")

        fold_results.append(eval_result)

        # Test each edge threshold
        print(f"  {'Threshold':<10} {'Bets':>6} {'HitRate':>8} {'P&L':>8} {'ROI':>8}")
        print(f"  {'-'*42}")

        threshold_results = {}
        for threshold in EDGE_THRESHOLDS:
            bets = _simulate_bets(bet_candidates, threshold)
            n = len(bets)
            if n == 0:
                print(f"  {threshold:<10.0%} {0:>6} {'-':>8} {'-':>8} {'-':>8}")
                threshold_results[threshold] = {"bets": 0, "pl": 0, "roi": 0, "hit_rate": 0}
                continue

            total_pl = sum(b["pl"] for b in bets)
            roi = total_pl / n
            hits = sum(1 for b in bets if b["pl"] > 0)
            hit_rate = hits / n

            print(f"  {threshold:<10.0%} {n:>6} {hit_rate:>7.1%} {total_pl:>+7.2f} {roi:>+7.1%}")
            threshold_results[threshold] = {
                "bets": n, "pl": round(total_pl, 2),
                "roi": round(roi, 4), "hit_rate": round(hit_rate, 4),
            }

        all_fold_data.append({
            "test_season": test_season,
            "n_matches": len(test_matches),
            "n_candidates": len(bet_candidates),
            "brier": eval_result.brier_score,
            "accuracy": eval_result.accuracy,
            "thresholds": {f"{k:.0%}": v for k, v in threshold_results.items()},
        })

    # ================================================================
    # Find best threshold
    # ================================================================
    best_threshold = None
    best_avg_roi = float("-inf")
    for t in EDGE_THRESHOLDS:
        rois = []
        for fd in all_fold_data:
            key = f"{t:.0%}"
            if key in fd["thresholds"] and fd["thresholds"][key]["bets"] > 10:
                rois.append(fd["thresholds"][key]["roi"])
        if rois:
            avg_roi = sum(rois) / len(rois)
            if avg_roi > best_avg_roi:
                best_avg_roi = avg_roi
                best_threshold = t

    # ================================================================
    # Report
    # ================================================================
    summary = backtest_summary(fold_results)
    report = {
        "backtest_date": _today_str(),
        "folds": all_fold_data,
        "summary": summary,
        "gate_result": "PASS" if summary["all_folds_beat_baseline"] else "FAIL",
        "best_threshold": f"{best_threshold:.0%}" if best_threshold else "none",
        "best_avg_roi": round(best_avg_roi, 4) if best_threshold else 0,
    }

    report_path = os.path.join(output_dir, "backtest_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"BACKTEST GATE: {report['gate_result']}")
    print(f"{'='*60}")
    print(f"Avg Brier: {summary['avg_brier']}")
    print(f"Best threshold: {report['best_threshold']} (avg ROI: {report['best_avg_roi']:+.1%})")
    print(f"Report saved to {report_path}")

    if not summary["all_folds_beat_baseline"]:
        print("\n[FAIL] Model does not consistently beat baseline.")
        print("DO NOT DEPLOY.")

    return report


def _bayesian_fuse(pred: dict, odds: dict) -> dict:
    """Fuse model prediction with market odds via Bayesian update.

    Returns posterior probabilities and raw model-market edges.
    """
    from models.odds import implied_probability
    from models.bayesian import bayesian_update

    imp = implied_probability(odds["home"], odds["draw"], odds["away"])
    market_probs = [imp["home"], imp["draw"], imp["away"]]
    model_probs = [pred["home_win"], pred["draw"], pred["away_win"]]

    # Raw model-market edge
    raw_edges = {
        "home": round(model_probs[0] - market_probs[0], 4),
        "draw": round(model_probs[1] - market_probs[1], 4),
        "away": round(model_probs[2] - market_probs[2], 4),
    }

    # Bayesian fusion — fixed model_confidence (v3.1: was based on max_prob,
    # which amplified overconfidence. Now uses cold-start as the only discount.)
    model_conf = 0.35 if pred.get("cold_start", False) else 0.50

    update = bayesian_update(
        model_probs, market_probs,
        model_confidence=model_conf,
        market_margin=imp["margin"],
        market_dispersion=0.04,
    )

    return {
        "posterior": {
            "home": update.posterior[0],
            "draw": update.posterior[1],
            "away": update.posterior[2],
        },
        "raw_edges": raw_edges,
        "model_weight": update.model_weight,
        "market_weight": update.market_weight,
    }


def _simulate_bets(candidates: list[dict], edge_threshold: float) -> list[dict]:
    """Simulate bets using Bayesian posterior edge + Kelly sizing.

    Bet condition: posterior probability > market implied + threshold
    AND Kelly fraction > 0.01 (minimum bet size)

    Stake sizing: Kelly fraction × 1 unit (quarter-Kelly conservative)
    """
    from models.odds import implied_probability, kelly_criterion

    bets = []
    for c in candidates:
        best_odds = c["best_odds"]
        posterior = c["posterior"]
        actual = c["actual"]

        imp = implied_probability(best_odds["home"], best_odds["draw"], best_odds["away"])
        market_probs = [imp["home"], imp["draw"], imp["away"]]

        # Find best posterior edge
        edges = {
            "home": posterior["home"] - market_probs[0],
            "draw": posterior["draw"] - market_probs[1],
            "away": posterior["away"] - market_probs[2],
        }
        best_dir = max(edges, key=edges.get)
        best_edge = edges[best_dir]

        if best_edge < edge_threshold:
            continue

        # Kelly sizing
        p_idx = {"home": 0, "draw": 1, "away": 2}[best_dir]
        kelly = kelly_criterion(
            posterior[best_dir],
            best_odds[best_dir],
            fraction=KELLY_FRACTION,
        )

        if kelly < 0.01:  # less than 1% of bankroll — skip
            continue

        # Simulate result
        odds_used = best_odds[best_dir]
        if best_dir == "home" and actual == "H":
            won = True
        elif best_dir == "draw" and actual == "D":
            won = True
        elif best_dir == "away" and actual == "A":
            won = True
        else:
            won = False

        stake = kelly  # stake as fraction of 1 unit
        pl = stake * (odds_used - 1) if won else -stake

        bets.append({
            "direction": best_dir,
            "odds": odds_used,
            "edge": round(best_edge, 4),
            "kelly": round(kelly, 4),
            "stake": round(stake, 4),
            "pl": round(pl, 4),
            "won": won,
        })

    return bets


def _get_best_odds(market_odds: dict) -> dict | None:
    """Get best (highest) odds across bookmakers."""
    if not market_odds:
        return None

    best = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for bookmaker, odds in market_odds.items():
        for k in ("home", "draw", "away"):
            if odds.get(k, 0) > best[k]:
                best[k] = odds[k]

    return best if best["home"] > 1.0 else None


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()
