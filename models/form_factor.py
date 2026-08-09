"""
Recent Form Factor — Exponential Weighted Moving Average

Addresses the static-model weakness: current Dixon-Coles uses only long-term
attack/defense parameters, missing team streaks/slumps.

Key design:
- Form factors are multiplicative adjustments to attack/defense in λ calculation
- Computed CHRONOLOGICALLY: only matches BEFORE the target match count
- Shrinkage toward 1.0: a team needs many matches for form to deviate significantly
- Tight clipping [0.75, 1.33] prevents extreme adjustments

Critical lesson from v1: cross-season form is noise (teams change too much).
Only within-season form (current campaign) is predictive.
"""
from __future__ import annotations

import math
from typing import Any


def compute_form_factors(
    recent_matches: list[dict],
    team_attack: dict[str, float],
    team_defense: dict[str, float],
    league_avg_goals: dict[str, float],
    league_home_adv: dict[str, float],
    n_recent: int = 5,
    half_life: int = 3,
    clip_range: tuple[float, float] = (0.70, 1.43),
    shrinkage_k: float = 5.0,
) -> dict[str, dict[str, float]]:
    """Compute per-team attack/defense form factors from recent matches.

    CRITICAL: `recent_matches` must be chronologically ordered and must ONLY
    contain matches that happened BEFORE the target prediction date.
    Cross-season form is NOT predictive — use current-season matches only,
    or at most the last 2-3 matches of the previous season.

    Args:
        recent_matches: chronologically ordered list of match dicts
        team_attack: long-term attack parameters
        team_defense: long-term defense parameters
        league_avg_goals: per-league average total goals
        league_home_adv: per-league home advantage
        n_recent: max number of recent matches to consider
        half_life: matches after which weight decays to 0.5
        clip_range: (min, max) for raw form factors
        shrinkage_k: regularization — form = 1 + (raw-1)*n/(n+k)

    Returns:
        {team_name: {'attack_form': float, 'defense_form': float, 'n_matches': int}}
    """
    # ── Exponential decay weights ──
    decay = 0.5 ** (1.0 / half_life)
    weights = [decay ** i for i in range(n_recent)]
    weights = [w / sum(weights) for w in weights]  # normalize

    # ── Accumulate per-team stats ──
    team_data: dict[str, dict] = {}
    for m in recent_matches:
        home = m["home_team"]
        away = m["away_team"]
        league = m.get("league_code", "")
        gh = m["home_goals"]
        ga = m["away_goals"]

        for team in (home, away):
            if team not in team_data:
                team_data[team] = {
                    "actual_gf": [],
                    "actual_ga": [],
                    "expected_gf": [],
                    "expected_ga": [],
                }

        # Expected goals from long-term parameters
        avg_g = league_avg_goals.get(league, 2.65)
        ha = league_home_adv.get(league, 0.30)
        att_h = team_attack.get(home, 1.0)
        def_h = team_defense.get(home, 1.0)
        att_a = team_attack.get(away, 1.0)
        def_a = team_defense.get(away, 1.0)

        exp_h = (avg_g / 2.0) * att_h * def_a * (1.0 + ha)
        exp_a = (avg_g / 2.0) * att_a * def_h

        team_data[home]["actual_gf"].append(gh)
        team_data[home]["actual_ga"].append(ga)
        team_data[home]["expected_gf"].append(exp_h)
        team_data[home]["expected_ga"].append(exp_a)

        team_data[away]["actual_gf"].append(ga)
        team_data[away]["actual_ga"].append(gh)
        team_data[away]["expected_gf"].append(exp_a)
        team_data[away]["expected_ga"].append(exp_h)

    # ── Compute weighted form ratios with shrinkage ──
    form_factors: dict[str, dict[str, float]] = {}

    for team, data in team_data.items():
        n_available = min(len(data["actual_gf"]), n_recent)
        if n_available < 3:
            form_factors[team] = {"attack_form": 1.0, "defense_form": 1.0, "n_matches": n_available}
            continue

        recent_gf = data["actual_gf"][-n_available:]
        recent_ga = data["actual_ga"][-n_available:]
        recent_exp_gf = data["expected_gf"][-n_available:]
        recent_exp_ga = data["expected_ga"][-n_available:]

        w = weights[-n_available:]

        w_gf = sum(w[i] * recent_gf[i] for i in range(n_available))
        w_ga = sum(w[i] * recent_ga[i] for i in range(n_available))
        w_exp_gf = sum(w[i] * recent_exp_gf[i] for i in range(n_available))
        w_exp_ga = sum(w[i] * recent_exp_ga[i] for i in range(n_available))

        # Raw form ratio
        raw_att = w_gf / max(w_exp_gf, 0.5)
        raw_def = w_ga / max(w_exp_ga, 0.5)

        # Clip
        lo, hi = clip_range
        raw_att = max(lo, min(hi, raw_att))
        raw_def = max(lo, min(hi, raw_def))

        # Shrink toward 1.0 based on evidence strength
        # form = 1.0 + (raw - 1.0) * n / (n + k)
        shrink = n_available / (n_available + shrinkage_k)
        attack_form = 1.0 + (raw_att - 1.0) * shrink
        defense_form = 1.0 + (raw_def - 1.0) * shrink

        form_factors[team] = {
            "attack_form": round(attack_form, 4),
            "defense_form": round(defense_form, 4),
            "n_matches": n_available,
        }

    return form_factors


def apply_form_to_lambda(
    base_lam_h: float,
    base_lam_a: float,
    home_team: str,
    away_team: str,
    form_factors: dict[str, dict[str, float]],
    blend_weight: float = 0.15,
) -> tuple[float, float]:
    """Apply form factors with partial blending.

    Instead of full multiplicative adjustment, uses a blend:
      λ_final = (1-w) * λ_base + w * λ_form

    This is more conservative and prevents over-amplification.
    blend_weight=0.15 means form only accounts for 15% of the λ.
    """
    hf = form_factors.get(home_team, {"attack_form": 1.0, "defense_form": 1.0})
    af = form_factors.get(away_team, {"attack_form": 1.0, "defense_form": 1.0})

    f_att_h = hf.get("attack_form", 1.0)
    f_def_h = hf.get("defense_form", 1.0)
    f_att_a = af.get("attack_form", 1.0)
    f_def_a = af.get("defense_form", 1.0)

    lam_h_form = base_lam_h * f_att_h * f_def_a
    lam_a_form = base_lam_a * f_att_a * f_def_h

    lam_h = (1 - blend_weight) * base_lam_h + blend_weight * lam_h_form
    lam_a = (1 - blend_weight) * base_lam_a + blend_weight * lam_a_form

    return lam_h, lam_a
