#!/usr/bin/env python
"""
Football Prediction Pipeline v3.0 — Single Entry Point

Usage:
  python pipeline.py train              # Fit ELO + Dixon-Coles from 25 CSVs
  python pipeline.py backtest           # Time-series CV, must beat baseline
  python pipeline.py predict            # Predict today's matches (needs odds API)
  python pipeline.py review YYYY-MM-DD  # Evaluate predictions vs results
  python pipeline.py full               # train → backtest → (predict if passed)
  python pipeline.py summary            # Show model state summary

Design principles:
  1. Data-first: all model parameters learned from historical CSVs
  2. One model: Dixon-Coles, not five disconnected bases
  3. Gated deployment: backtesting must pass before live prediction
  4. Single responsibility: each command does one thing well
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def cmd_train(args):
    """Train ELO and Dixon-Coles from historical CSV data."""
    from pipeline.data_loader import load_all_csvs
    from pipeline.trainer import train_all

    csv_dir = args.csv_dir or "data/historical_odds"
    state_dir = args.state_dir or "data/state"

    print(f"Loading CSVs from {csv_dir}...")
    matches = load_all_csvs(csv_dir)
    print(f"Loaded {len(matches)} matches from {len(set(m['season'] for m in matches))} seasons")
    print(f"Leagues: {set(m['league_code'] for m in matches)}")

    summary = train_all(matches, state_dir, use_mle=args.mle)

    print(f"\n[OK] Training complete")
    print(f"  Teams with ELO: {summary['elo']['teams']}")
    print(f"  Teams with attack/defense: {summary['dc_teams']}")
    print(f"  Leagues trained: {summary['leagues']}")
    print(f"  Fit method: {summary['fit_method']}")
    print(f"  State saved to {state_dir}/")


def cmd_backtest(args):
    """Run time-series cross-validation backtest."""
    from pipeline.data_loader import load_all_csvs
    from pipeline.backtester import run_backtest

    csv_dir = args.csv_dir or "data/historical_odds"
    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"

    print("Loading CSVs...")
    matches = load_all_csvs(csv_dir)

    report = run_backtest(matches, state_dir, output_dir)

    if report.get("gate_result") == "FAIL":
        print("\n⚠ BACKTEST GATE FAILED — model cannot be deployed")
        if not args.force:
            sys.exit(1)
    else:
        print("\n[PASS] BACKTEST GATE PASSED — model ready for deployment")


def cmd_predict(args):
    """Generate predictions for today's matches."""
    from pipeline.trainer import load_models
    from models.dixon_coles import dc_marginals

    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"

    # Load trained models
    try:
        elo, dc = load_models(state_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Loaded: {elo.team_count} ELO ratings, {dc.team_count} DC parameters")

    # Try to fetch live odds
    try:
        from pipeline.odds_fetcher import fetch_today_matches
        matches = fetch_today_matches()
        print(f"Fetched {len(matches)} matches from odds API")
    except Exception as e:
        print(f"Odds API unavailable: {e}")
        print("Provide matches via --matches-json")
        if not args.matches_json:
            sys.exit(1)
        matches = None

    # Or load from JSON
    if args.matches_json:
        with open(args.matches_json, "r", encoding="utf-8") as f:
            matches = json.load(f)
        print(f"Loaded {len(matches)} matches from {args.matches_json}")

    if not matches:
        print("No matches to predict.")
        return

    # Predict each match
    predictions = []
    for m in matches:
        home = m.get("home_team") or m.get("home")
        away = m.get("away_team") or m.get("away")
        league = m.get("league_code") or m.get("league", "PL")

        if not home or not away:
            continue

        pred = dc.predict(home, away, league)
        elo_h = elo.get_elo(home, league)
        elo_a = elo.get_elo(away, league)

        # Market comparison
        market = m.get("odds") or m.get("market_odds")
        if market:
            from models.odds import detect_value, implied_probability
            from models.bayesian import bayesian_fusion_predict

            value = detect_value(
                [pred["home_win"], pred["draw"], pred["away_win"]],
                market,
            )
            bayes = bayesian_fusion_predict(
                [pred["home_win"], pred["draw"], pred["away_win"]],
                market,
                model_confidence=0.5,
            )
        else:
            value = None
            bayes = None

        predictions.append({
            "home_team": home,
            "away_team": away,
            "league_code": league,
            "elo_home": elo_h,
            "elo_away": elo_a,
            "elo_diff": round(elo_h - elo_a, 1),
            "model": pred,
            "value": {
                "home_edge": value.home_value,
                "draw_edge": value.draw_value,
                "away_edge": value.away_value,
                "best_direction": value.best_direction,
                "kelly": value.kelly_fraction,
                "confidence": value.confidence,
            } if value else None,
            "bayesian": bayes,
            "cold_start": pred.get("cold_start", False),
        })

    # Save JSON
    os.makedirs(output_dir, exist_ok=True)
    today_str = _today_str()
    out_path = os.path.join(output_dir, f"predictions_{today_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(predictions)} predictions to {out_path}")

    # Generate HTML report
    try:
        from pipeline.reporter import generate_report
        html_path = generate_report(predictions, output_dir)
        print(f"HTML report: {html_path}")
    except Exception as e:
        print(f"HTML report generation failed: {e}")

    # Print summary table
    print(f"\n{'Home':<20} {'Away':<20} {'H':>6} {'D':>6} {'A':>6} {'Pick':>10} {'Edge':>6}")
    print("-" * 80)
    for p in predictions:
        m = p["model"]
        pick = "Home" if m["home_win"] >= m["away_win"] and m["home_win"] >= m["draw"] else \
               "Away" if m["away_win"] >= m["home_win"] and m["away_win"] >= m["draw"] else "Draw"
        edge_str = p["value"]["best_direction"] if p["value"] else "-"
        print(f"{p['home_team']:<20} {p['away_team']:<20} "
              f"{m['home_win']:>6.1%} {m['draw']:>6.1%} {m['away_win']:>6.1%} "
              f"{pick:>10} {edge_str:>6}")


def cmd_review(args):
    """Evaluate predictions against actual results."""
    date_str = args.date
    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"

    pred_path = os.path.join(output_dir, f"predictions_{date_str}.json")
    if not os.path.exists(pred_path):
        print(f"No predictions found for {date_str} at {pred_path}")
        sys.exit(1)

    with open(pred_path, "r", encoding="utf-8") as f:
        predictions = json.load(f)

    # Expect results JSON: [{"home_team": "...", "away_team": "...", "result": "H"}]
    results_path = args.results_json or os.path.join(output_dir, f"results_{date_str}.json")
    if not os.path.exists(results_path):
        print(f"No results file at {results_path}")
        print("Create a JSON file with: [{\"home_team\": \"...\", \"away_team\": \"...\", "
              "\"home_goals\": 2, \"away_goals\": 1, \"result\": \"H\"}]")
        sys.exit(1)

    with open(results_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    # Match predictions to results
    from models.evaluation import lockbox_evaluate

    eval_data = []
    for pred in predictions:
        home = pred["home_team"]
        away = pred["away_team"]
        # Find matching result
        actual = None
        for r in results:
            if (r.get("home_team") == home and r.get("away_team") == away) or \
               (r.get("home") == home and r.get("away") == away):
                actual = r.get("result")
                break

        if actual:
            eval_data.append({
                "home_win": pred["model"]["home_win"],
                "draw": pred["model"]["draw"],
                "away_win": pred["model"]["away_win"],
                "actual": actual,
            })

    if not eval_data:
        print("No matching predictions and results found.")
        return

    result = lockbox_evaluate(eval_data)
    print(f"\nReview for {date_str}:")
    print(f"  Matches: {result.n_matches}")
    print(f"  Brier:   {result.brier_score}")
    print(f"  Accuracy: {result.accuracy:.1%}")
    print(f"  Baseline Brier: {result.baseline_brier}")
    print(f"  Beats baseline: {result.beats_baseline}")
    print(f"  Verdict: {result.verdict}")

    # Update ELO from results
    elo = None
    try:
        from models.elo import EloSystem
        elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
        elo.load()
    except Exception:
        pass

    if elo:
        for r in results:
            home = r.get("home_team") or r.get("home")
            away = r.get("away_team") or r.get("away")
            gh = r.get("home_goals", 0)
            ga = r.get("away_goals", 0)
            league = r.get("league_code", "")
            if home and away:
                ha = elo._league_home_advantage.get(league, 100)
                elo_h = elo.get_elo(home, league)
                elo_a = elo.get_elo(away, league)
                new_h, new_a = elo._update_match(elo_h, elo_a, gh, ga, ha)
                elo._ratings[home] = new_h
                elo._ratings[away] = new_a
        elo.save()
        print(f"  → ELO updated for {len(results)} matches")


def cmd_summary(args):
    """Print model training summary."""
    state_dir = args.state_dir or "data/state"
    summary_path = os.path.join(state_dir, "training_summary.json")

    if not os.path.exists(summary_path):
        print("No training summary found. Run 'train' first.")
        return

    with open(summary_path, "r", encoding="utf-8") as f:
        s = json.load(f)

    print(f"Training Summary")
    print(f"{'='*60}")
    print(f"Total matches:  {s['total_matches']}")
    print(f"ELO teams:      {s['elo']['teams']}")
    print(f"DC teams:       {s['dc_teams']}")
    print(f"Leagues:        {', '.join(s['leagues'])}")
    print(f"Fit method:     {s['fit_method']}")
    print(f"\nELO Stats:")
    print(f"  Range: {s['elo']['min']} – {s['elo']['max']}")
    print(f"  Mean:  {s['elo']['mean']}")
    print(f"\nTop 10:")
    for team, rating in s['elo']['top_10']:
        print(f"  {team:<25} {rating}")

    # Show league parameters
    print(f"\nLeague Parameters:")
    for code, params in s.get("league_params", {}).items():
        print(f"  {code}: ρ={params['rho']:.4f}, home_adv={params['home_adv']:.4f}, "
              f"avg_goals={params['avg_goals']}")


def cmd_full(args):
    """Run the complete pipeline: train → backtest → (predict)."""
    print("=" * 60)
    print("FULL PIPELINE")
    print("=" * 60)

    # Step 1: Train
    print("\n[1/3] TRAINING")
    cmd_train(args)

    # Step 2: Backtest
    print("\n[2/3] BACKTEST")
    try:
        cmd_backtest(args)
    except SystemExit as e:
        if e.code == 1:
            print("\nPipeline stopped: backtest gate failed.")
            return
        raise

    # Step 3: Predict (if --predict flag)
    if args.predict_live:
        print("\n[3/3] LIVE PREDICTION")
        cmd_predict(args)
    else:
        print("\n[3/3] SKIPPED (use --predict for live predictions)")


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()


def main():
    parser = argparse.ArgumentParser(
        description="Football Prediction Pipeline v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  train      Fit ELO + Dixon-Coles from 25 historical CSVs
  backtest   Time-series cross-validation (must beat baseline)
  predict    Generate predictions for today's matches
  review     Evaluate prediction accuracy vs actual results
  full       Run train → backtest → predict in sequence
  summary    Show model state

Examples:
  python pipeline.py train
  python pipeline.py backtest
  python pipeline.py train --mle          # Use scipy MLE fitting
  python pipeline.py predict --matches-json data/today.json
  python pipeline.py review 2026-08-08
  python pipeline.py full --predict
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Common options
    def add_common(p):
        p.add_argument("--csv-dir", default="data/historical_odds", help="CSV directory")
        p.add_argument("--state-dir", default="data/state", help="Model state directory")
        p.add_argument("--output-dir", default="data/output", help="Output directory")

    # train
    p_train = subparsers.add_parser("train", help="Train models from historical data")
    add_common(p_train)
    p_train.add_argument("--mle", action="store_true",
                        help="Use scipy MLE (requires scipy)")

    # backtest
    p_backtest = subparsers.add_parser("backtest", help="Run time-series backtest")
    add_common(p_backtest)
    p_backtest.add_argument("--force", action="store_true",
                           help="Continue even if backtest gate fails")

    # predict
    p_predict = subparsers.add_parser("predict", help="Generate live predictions")
    add_common(p_predict)
    p_predict.add_argument("--matches-json", help="Path to match list JSON")
    p_predict.add_argument("--llm", action="store_true",
                          help="Add LLM qualitative analysis")

    # review
    p_review = subparsers.add_parser("review", help="Evaluate predictions vs results")
    add_common(p_review)
    p_review.add_argument("date", help="Date of predictions (YYYY-MM-DD)")
    p_review.add_argument("--results-json", help="Path to results JSON")

    # full
    p_full = subparsers.add_parser("full", help="Run complete pipeline")
    add_common(p_full)
    p_full.add_argument("--predict", dest="predict_live", action="store_true",
                       help="Also run live predictions after backtest")
    p_full.add_argument("--mle", action="store_true", help="Use scipy MLE")

    # summary
    p_summary = subparsers.add_parser("summary", help="Show training summary")
    add_common(p_summary)

    args = parser.parse_args()

    if args.command == "train":
        cmd_train(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "predict":
        cmd_predict(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "full":
        cmd_full(args)
    elif args.command == "summary":
        cmd_summary(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
