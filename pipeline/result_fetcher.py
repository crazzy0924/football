"""
Result Fetcher v3.0

Fetches post-match results for review and ELO update.
Supports: manual JSON, odds-api.io results, auto-derivation from scores.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pipeline.data_loader import normalize_team_name


def load_results_from_json(path: str) -> list[dict]:
    """Load match results from a JSON file.

    Expected format:
    [
        {
            "home_team": "Liverpool",
            "away_team": "Arsenal",
            "home_goals": 2,
            "away_goals": 1,
            "result": "H"    ← optional, derived from goals if missing
        },
        ...
    ]
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Results file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return _normalize_results(data)


def load_results_from_text(text: str) -> list[dict]:
    """Parse results from a simple text format.

    Format (one per line):
      HomeTeam 2-1 AwayTeam
      HomeTeam 0-0 AwayTeam
      HomeTeam 1-3 AwayTeam

    Lines starting with # are comments.
    Blank lines are skipped.
    """
    results = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Try "TeamA X-Y TeamB" format
        import re
        m = re.match(r"(.+?)\s+(\d+)\s*[-–—]\s*(\d+)\s+(.+)", line)
        if m:
            home_team = m.group(1).strip()
            home_goals = int(m.group(2))
            away_goals = int(m.group(3))
            away_team = m.group(4).strip()
            results.append({
                "home_team": home_team,
                "away_team": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
            })
            continue

        # Try JSON-like inline
        try:
            obj = json.loads(line)
            if "home_team" in obj or "home" in obj:
                results.append(obj)
        except (json.JSONDecodeError, ValueError):
            pass

    return _normalize_results(results)


def try_fetch_results(date_str: str) -> list[dict] | None:
    """Try to fetch results from odds-api.io for a given date.

    Returns None if API is unavailable.
    """
    try:
        from config import ODDS_API_KEY
        if not ODDS_API_KEY:
            return None
    except Exception:
        return None

    try:
        import urllib.request
        import urllib.error

        url = (
            f"https://api.odds-api.io/v4/sports/soccer_epl/scores/"
            f"?apiKey={ODDS_API_KEY}&date={date_str}"
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for game in data.get("data", []):
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            scores = game.get("scores") or {}
            hg = scores.get("home")
            ag = scores.get("away")
            if home and away and hg is not None and ag is not None:
                results.append({
                    "home_team": home,
                    "away_team": away,
                    "home_goals": int(hg),
                    "away_goals": int(ag),
                })
        return _normalize_results(results) if results else None
    except Exception:
        return None


def _normalize_results(data: list[dict]) -> list[dict]:
    """Normalize and validate results data."""
    results = []
    for item in data:
        # Normalize field names
        home = item.get("home_team") or item.get("home", "")
        away = item.get("away_team") or item.get("away", "")
        if not home or not away:
            continue

        home = normalize_team_name(home)
        away = normalize_team_name(away)

        # Derive result from goals if missing
        if "result" not in item:
            hg = item.get("home_goals")
            ag = item.get("away_goals")
            if hg is not None and ag is not None:
                hg = int(hg)
                ag = int(ag)
                result = "H" if hg > ag else "D" if hg == ag else "A"
            else:
                result = None
        else:
            result = item["result"]
            hg = item.get("home_goals")
            ag = item.get("away_goals")

        results.append({
            "home_team": home,
            "away_team": away,
            "home_goals": int(hg) if hg is not None else None,
            "away_goals": int(ag) if ag is not None else None,
            "result": result,
        })

    return results


def match_predictions_to_results(
    predictions: list[dict],
    results: list[dict],
) -> list[dict]:
    """Match predictions to results with fuzzy team name matching.

    Returns list of matched pairs:
    [
        {
            "home_team": "...", "away_team": "...",
            "predicted": {"home_win": 0.45, "draw": 0.28, "away_win": 0.27},
            "actual": "H",
            "home_goals": 2, "away_goals": 1,
            "value": {...},  # from prediction
            "matched": True,
        },
        ...
    ]
    """
    matched = []
    unmatched_pred = []
    unmatched_res = list(results)

    for pred in predictions:
        ph = normalize_team_name(pred.get("home_team", ""))
        pa = normalize_team_name(pred.get("away_team", ""))

        found = None
        for i, res in enumerate(unmatched_res):
            rh = normalize_team_name(res.get("home_team", ""))
            ra = normalize_team_name(res.get("away_team", ""))
            if _teams_match(ph, rh) and _teams_match(pa, ra):
                found = unmatched_res.pop(i)
                break

        if found:
            model = pred.get("model", {})
            matched.append({
                "home_team": ph,
                "away_team": pa,
                "league_code": pred.get("league_code", ""),
                "predicted": {
                    "home_win": model.get("home_win", 0.33),
                    "draw": model.get("draw", 0.34),
                    "away_win": model.get("away_win", 0.33),
                },
                "actual": found["result"],
                "home_goals": found.get("home_goals"),
                "away_goals": found.get("away_goals"),
                "value": pred.get("value"),
                "bayesian": pred.get("bayesian"),
                "elo_diff": pred.get("elo_diff", 0),
                "cold_start": pred.get("cold_start", False),
                "matched": True,
            })
        else:
            unmatched_pred.append(pred)

    if unmatched_pred:
        print(f"  [WARN] {len(unmatched_pred)} predictions could not be matched to results")

    return matched


def _teams_match(a: str, b: str) -> bool:
    """Fuzzy team name matching."""
    if not a or not b:
        return False
    a = a.lower().replace(" ", "").replace(".", "").replace("'", "")
    b = b.lower().replace(" ", "").replace(".", "").replace("'", "")
    return a == b or a in b or b in a
