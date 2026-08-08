"""
Result Fetcher v3.0

Fetches post-match results for review and ELO update.
Supports manual JSON entry and (future) API-based fetching.
"""
from __future__ import annotations

import json
import os
from typing import Any


def load_results_from_json(path: str) -> list[dict]:
    """Load match results from a JSON file.

    Expected format:
    [
        {
            "home_team": "Liverpool",
            "away_team": "Arsenal",
            "home_goals": 2,
            "away_goals": 1,
            "result": "H"
        },
        ...
    ]
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Results file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate
    for item in data:
        if "home_team" not in item and "home" in item:
            item["home_team"] = item["home"]
        if "away_team" not in item and "away" in item:
            item["away_team"] = item["away"]
        if "result" not in item and "home_goals" in item:
            hg = item["home_goals"]
            ag = item["away_goals"]
            item["result"] = "H" if hg > ag else "D" if hg == ag else "A"

    return data
