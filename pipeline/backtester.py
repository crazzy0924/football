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


# 投注策略参数
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
    print(f"测试边缘阈值: {[f'{t:.0%}' for t in EDGE_THRESHOLDS]}")

    if len(seasons) < 3:
        return {"error": f"Need at least 3 seasons, got {len(seasons)}"}

    test_seasons = seasons[-n_folds:]
    fold_results = []
    all_fold_data = []

    for test_season in test_seasons:
        print(f"\n{'='*60}")
        print(f"折: 测试 {test_season}")
        print(f"{'='*60}")

        train_seasons = [s for s in seasons if s < test_season]
        train_matches = [m for m in matches if m["season"] in train_seasons]
        test_matches = [m for m in matches if m["season"] == test_season]

        print(f"训练: {len(train_matches)} 场 来自 {train_seasons}")
        print(f"测试: {len(test_matches)} 场 来自 {test_season}")

        if len(train_matches) < 100 or len(test_matches) < 50:
            continue

        # 仅用历史数据训练
        elo = EloSystem()
        elo.initialize_from_matches(train_matches)

        dc = DixonColesModel()
        try:
            dc.fit_mle(train_matches)
        except Exception as e:
            print(f"  MLE失败 ({e}), 回退到 fit_simple")
            dc.fit_simple(train_matches)

        # ── 平局校准: 联赛级事后修正 ──
        from models.draw_calibration import fit_draw_calibration, apply_draw_calibration
        draw_cal = fit_draw_calibration(train_matches, dc)
        n_cal_leagues = len(draw_cal)
        boosted = sum(1 for v in draw_cal.values() if v["draw_factor"] > 1.01)
        print(f"  平局校准: {n_cal_leagues} 个联赛, {boosted} 个平局加成")

        # ── Phase 2: 概率校准 (训练折拟合, 测试折应用) ──
        from models.calibration import fit_calibration, apply_calibration as apply_prob_cal
        print("  拟合概率校准(训练折)...")
        train_preds = []
        train_actuals = []
        train_leagues = []
        for tm in train_matches:
            if tm["result"] not in ("H", "D", "A"):
                continue
            tp = dc.predict(tm["home_team"], tm["away_team"], tm["league_code"])
            train_preds.append([tp["home_win"], tp["draw"], tp["away_win"]])
            train_actuals.append({"H": 0, "D": 1, "A": 2}[tm["result"]])
            train_leagues.append(tm["league_code"])
        prob_cal = fit_calibration(train_preds, train_actuals, leagues=train_leagues)
        n_lg = len((prob_cal.get("curves_by_league") or {}))
        print(f"  概率校准: 拟合于 {len(train_actuals)} 场训练赛, {n_lg} 个联赛独立曲线")

        league_stats = compute_league_stats(train_matches)

        # ── 近期状态: 测试赛季内按时间顺序处理 ──
        # 维护已完赛池 (训练 + 已见过的测试赛)
        # 每场测试赛前重算状态因子。
        # 确保状态只用赛前已有数据。
        from models.form_factor import compute_form_factors
        completed_matches = list(train_matches)  # start with all training data (prev seasons)

        # 按时间排序测试赛 (本已有序, 双保险)
        test_matches_sorted = sorted(test_matches, key=lambda m: (
            m.get("date", ""), m.get("kickoff", ""), m.get("commence_time", "")
        ))

        # 预测全部测试赛
        predictions = []
        bet_candidates = []
        ah_predictions = []

        # 记录状态重算次数 (每50场重算一次, 省时)
        form_cache = None
        form_cache_matches = -1
        form_recompute_interval = 50  # recompute after every N new matches

        for idx, m in enumerate(test_matches_sorted):
            # 定期重算状态因子, 或缓存过期时
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

            # 对原始DC概率应用平局校准
            cal_h, cal_d, cal_a = apply_draw_calibration(
                {"home_win": pred["home_win"], "draw": pred["draw"], "away_win": pred["away_win"]},
                m["league_code"], draw_cal,
            )
            cal_pred = {"home_win": cal_h, "draw": cal_d, "away_win": cal_a}

            # Phase 2: 概率校准 (全局+分联赛, 融合仍用原始, Brier并列报告)
            cc_h, cc_d, cc_a = apply_prob_cal([cal_h, cal_d, cal_a], prob_cal, m["league_code"])

            # Phase 2b: ELO-DC 混合 (30% ELO 方向概率 + 70% DC)
            elo_h = elo.get_elo(m["home_team"], m["league_code"])
            elo_a = elo.get_elo(m["away_team"], m["league_code"])
            ha_elo = elo._league_home_advantage.get(m["league_code"], 100)
            diff_h = elo_h + ha_elo - elo_a
            p_h_elo = 1.0 / (1.0 + 10 ** (-diff_h / 400.0))
            p_a_elo = 1.0 / (1.0 + 10 ** (-(-diff_h) / 400.0))
            p_d_elo = max(0.02, 1.0 - p_h_elo - p_a_elo)
            s_elo = p_h_elo + p_d_elo + p_a_elo
            W_ELO = 0.30
            bl_h = W_ELO * p_h_elo / s_elo + (1 - W_ELO) * cal_h
            bl_d = W_ELO * p_d_elo / s_elo + (1 - W_ELO) * cal_d
            bl_a = W_ELO * p_a_elo / s_elo + (1 - W_ELO) * cal_a

            market_odds = m.get("odds", {})
            best_odds = _get_best_odds(market_odds)

            # 用校准后的模型概率做贝叶斯融合
            if best_odds:
                bayes_result = _bayesian_fuse(cal_pred, best_odds, cold_start=pred.get("cold_start", False))
            else:
                bayes_result = None

            predictions.append({
                "home_win": cal_h,
                "draw": cal_d,
                "away_win": cal_a,
                "cal_home_win": cc_h,
                "cal_draw": cc_d,
                "cal_away_win": cc_a,
                "bl_home_win": bl_h,
                "bl_draw": bl_d,
                "bl_away_win": bl_a,
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
                    "model_probs": [cal_h, cal_d, cal_a],
                    "posterior": bayes_result["posterior"],
                    "raw_edge": bayes_result["raw_edges"],
                })

            # ── 让球盘预测 ──
            ah_line = m.get("ah_line")
            ah_odds = m.get("ah_odds")
            if ah_line is not None and ah_odds:
                from pipeline.five_dim_predictor import compute_handicap_probs
                ah_probs = compute_handicap_probs(pred["score_distribution"], ah_line)
                ah_predictions.append({
                    "home_team": m["home_team"],
                    "away_team": m["away_team"],
                    "goal_line": ah_line,
                    "model_cover": ah_probs["home_cover"],
                    "model_push": ah_probs["push"],
                    "model_lose": ah_probs["away_cover"],
                    "ah_odds": ah_odds,
                    "home_goals": m["home_goals"],
                    "away_goals": m["away_goals"],
                    "league_code": m["league_code"],
                })

            # 赛果回灌状态池 (时间序 — 只用已完赛数据)
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
        print(f"  Brier: {eval_result.brier_score} (基线: {eval_result.baseline_brier})")
        print(f"  准确率: {eval_result.accuracy:.1%}")

        # Phase 2: 校准后 Brier 并列报告 (与 brier_score 同口径: 三结果平方误差和)
        cal_brier = 0.0
        for p in predictions:
            av = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}[p["actual"]]
            cal_brier += sum((q - v) ** 2 for q, v in zip(
                [p["cal_home_win"], p["cal_draw"], p["cal_away_win"]], av
            ))
        cal_brier /= max(len(predictions), 1)
        print(f"  校准后Brier(分联赛): {cal_brier:.4f} (差 {cal_brier - eval_result.brier_score:+.4f})")

        # Phase 2b: ELO混合 Brier
        bl_brier = 0.0
        for p in predictions:
            av = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}[p["actual"]]
            bl_brier += sum((q - v) ** 2 for q, v in zip(
                [p["bl_home_win"], p["bl_draw"], p["bl_away_win"]], av
            ))
        bl_brier /= max(len(predictions), 1)
        print(f"  ELO混合Brier(30/70): {bl_brier:.4f} (差 {bl_brier - eval_result.brier_score:+.4f})")

        fold_results.append(eval_result)

        # 测试各边缘阈值
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

            print(f"  阈值{threshold:<6.0%} {n:>6}注 {hit_rate:>6.1%} {total_pl:>+7.2f} {roi:>+7.1%}")
            threshold_results[threshold] = {
                "bets": n, "pl": round(total_pl, 2),
                "roi": round(roi, 4), "hit_rate": round(hit_rate, 4),
            }

        # ── 让球盘评估 ──
        if ah_predictions:
            ah_eval = _evaluate_ah(ah_predictions)
            print(f"  AH Brier: {ah_eval['brier']:.4f} (baseline: 0.2500)")
            print(f"  让球准确率: {ah_eval['accuracy']:.1%}")
            print(f"  让球走盘率: {ah_eval['push_rate']:.1%}")
            print(f"  {'AH Edge':<10} {'Bets':>6} {'Hit%':>7} {'P&L':>8} {'ROI':>8}")
            print(f"  {'-'*42}")
            ah_thresholds = {}
            for threshold in [0.03, 0.05, 0.08, 0.10, 0.12]:
                ah_bets = _simulate_ah_bets(ah_predictions, threshold)
                n = len(ah_bets)
                if n == 0:
                    print(f"  {threshold:<10.0%} {0:>6} {'-':>7} {'-':>8} {'-':>8}")
                    ah_thresholds[threshold] = {"bets": 0, "pl": 0, "roi": 0, "hit_rate": 0}
                else:
                    total_pl = sum(b["pl"] for b in ah_bets)
                    roi = total_pl / n
                    hits = sum(1 for b in ah_bets if b["pl"] > 0)
                    hit_rate = hits / n
                    print(f"  阈值{threshold:<6.0%} {n:>6}注 {hit_rate:>6.1%} {total_pl:>+7.2f} {roi:>+7.1%}")
                    ah_thresholds[threshold] = {
                        "bets": n, "pl": round(total_pl, 2),
                        "roi": round(roi, 4), "hit_rate": round(hit_rate, 4),
                    }
        else:
            ah_eval = {"brier": 0, "accuracy": 0, "push_rate": 0}
            ah_thresholds = {}

        all_fold_data.append({
            "test_season": test_season,
            "n_matches": len(test_matches),
            "n_candidates": len(bet_candidates),
            "brier": eval_result.brier_score,
            "accuracy": eval_result.accuracy,
            "thresholds": {f"{k:.0%}": v for k, v in threshold_results.items()},
            "ah_brier": ah_eval["brier"],
            "ah_accuracy": ah_eval["accuracy"],
            "ah_push_rate": ah_eval["push_rate"],
            "ah_thresholds": {f"{k:.0%}": v for k, v in ah_thresholds.items()},
        })

    # ================================================================
    # 寻找最佳阈值
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
    print(f"回测门禁: {report['gate_result']}")
    print(f"{'='*60}")
    print(f"Avg Brier: {summary['avg_brier']}")
    print(f"最佳阈值: {report['best_threshold']} (平均ROI: {report['best_avg_roi']:+.1%})")
    print(f"报告已保存至 {report_path}")

    if not summary["all_folds_beat_baseline"]:
        print("\n[未通过] 模型未能稳定击败基线。")
        print("DO NOT DEPLOY.")

    return report


def _bayesian_fuse(pred: dict, odds: dict, cold_start: bool = False) -> dict:
    """Fuse model prediction with market odds via Bayesian update.

    Returns posterior probabilities and raw model-market edges.
    """
    from models.odds import implied_probability
    from models.bayesian import bayesian_update

    imp = implied_probability(odds["home"], odds["draw"], odds["away"])
    market_probs = [imp["home"], imp["draw"], imp["away"]]
    model_probs = [pred["home_win"], pred["draw"], pred["away_win"]]

    # 原始模型-市场边缘
    raw_edges = {
        "home": round(model_probs[0] - market_probs[0], 4),
        "draw": round(model_probs[1] - market_probs[1], 4),
        "away": round(model_probs[2] - market_probs[2], 4),
    }

    # 贝叶斯融合 — 固定模型置信度 (v3.1: 曾基于max_prob,
    # 曾放大过度自信。现在仅以冷启动作为折价。)
    model_conf = 0.35 if cold_start else 0.50

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

        # 寻找最佳后验边缘
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


def _evaluate_ah(ah_predictions: list[dict]) -> dict:
    """Evaluate Asian Handicap predictions — binary outcome with push handling."""
    n_push = sum(1 for p in ah_predictions if p["model_push"] > 0.99 or
                 (p["home_goals"] - p["away_goals"] + p["goal_line"] == 0))
    non_push = [p for p in ah_predictions
                if p["home_goals"] - p["away_goals"] + p["goal_line"] != 0]

    if not non_push:
        return {"brier": 0, "accuracy": 0, "push_rate": 0}

    brier_sum = 0.0
    correct = 0
    for p in non_push:
        adj = p["home_goals"] - p["away_goals"] + p["goal_line"]
        actual = 1.0 if adj > 0 else 0.0
        brier_sum += (p["model_cover"] - actual) ** 2
        model_pick = 1 if p["model_cover"] > 0.5 else 0
        if model_pick == actual:
            correct += 1

    n = len(non_push)
    return {
        "brier": round(brier_sum / n, 4),
        "accuracy": round(correct / n, 4),
        "push_rate": round(n_push / len(ah_predictions), 4) if ah_predictions else 0,
    }


def _simulate_ah_bets(ah_predictions: list[dict], edge_threshold: float) -> list[dict]:
    """Simulate Asian Handicap bets using model-vs-market edge + Kelly sizing."""
    import math
    from models.odds import kelly_criterion

    bets = []
    for p in ah_predictions:
        # 走盘 = 不结算输赢 (退还本金)
        adj = p["home_goals"] - p["away_goals"] + p["goal_line"]
        if adj == 0:
            continue

        actual_covered = adj > 0
        ah_odds = p["ah_odds"]

        # Shin去水市场赔率 → 公平概率
        odds_h, odds_a = ah_odds["home"], ah_odds["away"]
        o = [1.0 / odds_h, 1.0 / odds_a]
        z0 = sum(o)
        margin = z0 - 1.0
        if margin <= 0:
            market_h_prob = o[0] / z0
        else:
            c = min(0.5, margin * 0.8)
            for _ in range(100):
                denom = sum(math.sqrt(c + (1 - c) * oi ** 2) for oi in o)
                probs = [math.sqrt(c + (1 - c) * oi ** 2) / denom for oi in o]
                c_new = c * sum((1 - pi) ** 2 for pi in probs) / (2 - sum(pi ** 2 for pi in probs))
                if abs(c_new - c) < 1e-7:
                    break
                c = c_new
            market_h_prob = probs[0]

        # 模型在主队覆盖上的边缘
        model_h_prob = p["model_cover"]
        edge = model_h_prob - market_h_prob

        if abs(edge) < edge_threshold:
            continue

        # 确定投注方向
        if edge > 0:
            bet_on = "home"
            fair_prob = model_h_prob
            odds_used = odds_h
        else:
            bet_on = "away"
            fair_prob = 1.0 - model_h_prob
            odds_used = odds_a

        # Kelly仓位: f* = (p*b - q) / b, 其中 b = 赔率 - 1
        b = odds_used - 1.0  # decimal odds → fractional
        if b <= 0:
            continue
        q = 1.0 - fair_prob
        kelly = (fair_prob * b - q) / b
        stake = max(0.0, min(0.05, kelly * 0.25))  # 1/4 Kelly, 5% max

        if stake < 0.01:
            continue

        won = (bet_on == "home" and actual_covered) or (bet_on == "away" and not actual_covered)
        pl = stake * b if won else -stake

        bets.append({
            "direction": bet_on + "_cover",
            "odds": round(odds_used, 2),
            "edge": round(edge, 4),
            "kelly": round(kelly, 4),
            "stake": round(stake, 4),
            "pl": round(pl, 4),
            "won": won,
        })

    return bets


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()
