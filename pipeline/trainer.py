"""
Model Trainer v3.0

Two-pass training pipeline:
1. ELO Calibration: chronologically replay all ~9,000 matches
2. Dixon-Coles Fitting: MLE of attack/defense/rho parameters

Input: list of match dicts from data_loader
Output: persisted ELO ratings + Dixon-Coles parameters
"""
from __future__ import annotations

import json
import os
from typing import Any

from models.elo import EloSystem
from models.dixon_coles import DixonColesModel
from models.league_profiles import LEAGUE_PROFILES, compute_league_profiles_from_matches


def train_all(
    matches: list[dict],
    state_dir: str = "data/state",
    use_mle: bool = True,
) -> dict[str, Any]:
    """Run the full training pipeline.

    Args:
        matches: chronological list of match dicts
        state_dir: directory for persisted state
        use_mle: if True, use scipy MLE; if False, use analytical fit

    Returns:
        Summary dict with training statistics
    """
    os.makedirs(state_dir, exist_ok=True)

    # ================================================================
    # Pass 1: ELO Calibration
    # ================================================================
    print(f"Pass 1: Calibrating ELO from {len(matches)} matches...")

    # Compute league profiles from actual data (overrides hardcoded values)
    data_profiles = compute_league_profiles_from_matches(matches)

    # Merge: use data-derived where available, fall back to hardcoded
    profiles_for_elo = {}
    for code in set(m["league_code"] for m in matches):
        if code in data_profiles:
            profiles_for_elo[code] = data_profiles[code]
        elif code in LEAGUE_PROFILES:
            profiles_for_elo[code] = LEAGUE_PROFILES[code]

    elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
    elo.initialize_from_matches(matches, profiles_for_elo)
    elo.save()
    print(f"  → {elo.team_count} teams with ELO ratings")

    # ================================================================
    # Pass 2: Dixon-Coles Fitting
    # ================================================================
    print("Pass 2: Fitting Dixon-Coles parameters...")

    dc = DixonColesModel()

    if use_mle:
        dc.fit_mle(matches)
        method = "MLE (scipy BFGS)"
    else:
        dc.fit_simple(matches)
        method = "Analytical (moment-based)"

    dc.save(state_dir)
    print(f"  → {dc.team_count} teams with attack/defense params")
    print(f"  → Method: {method}")

    # ================================================================
    # Summary
    # ================================================================
    summary = {
        "total_matches": len(matches),
        "elo": elo.ratings_summary,
        "dc_teams": dc.team_count,
        "leagues": list(dc.league_rho.keys()),
        "league_params": {
            code: {
                "rho": dc.league_rho.get(code, -0.10),
                "home_adv": dc.league_home_adv.get(code, 0.30),
                "avg_goals": dc.league_avg_goals.get(code, 2.65),
            }
            for code in dc.league_rho
        },
        "fit_method": method,
    }

    # Save summary
    summary_path = os.path.join(state_dir, "training_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def load_models(
    state_dir: str = "data/state",
) -> tuple[EloSystem, DixonColesModel]:
    """Load previously trained models from disk."""
    elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
    dc = DixonColesModel()

    if not elo.load():
        raise FileNotFoundError(
            f"ELO ratings not found at {state_dir}/elo_ratings.json. Run train first."
        )
    if not dc.load(state_dir):
        raise FileNotFoundError(
            f"Dixon-Coles params not found at {state_dir}. Run train first."
        )

    return elo, dc
