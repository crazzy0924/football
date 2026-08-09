"""
Dixon-Coles Model v3.0 — Core Prediction Engine

Extends the standard Poisson model with the Dixon & Coles (1997) ρ correction.
The ρ parameter corrects for systematic underestimation of 0-0, 1-0, 0-1, 1-1.

New in v3.0: DixonColesModel class with:
- Maximum likelihood fitting from historical data (scipy BFGS)
- Persistence via JSON save/load
- Team-level attack/defense parameters
- League-specific ρ and home advantage

Core math preserved from v2.0:
- tau(), dc_score_probability(), dc_score_matrix(), dc_marginals()
- estimate_rho() grid search
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

from models.poisson import poisson_pmf


# ============================================================
# Dixon-Coles τ correction (preserved from v2.0)
# ============================================================

def tau(gh: int, ga: int, lam_h: float, lam_a: float, rho: float) -> float:
    """Dixon-Coles τ correction factor.

    τ(0,0) = 1 - λh·λa·ρ     τ(1,0) = 1 + λh·ρ
    τ(0,1) = 1 + λa·ρ         τ(1,1) = 1 - ρ
    τ(other) = 1

    ρ range: typically -0.15 to 0.05 (negative = draws more likely)
    """
    if gh == 0 and ga == 0:
        return max(0.0, 1.0 - lam_h * lam_a * rho)
    elif gh == 1 and ga == 0:
        return max(0.0, 1.0 + lam_h * rho)
    elif gh == 0 and ga == 1:
        return max(0.0, 1.0 + lam_a * rho)
    elif gh == 1 and ga == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def dc_score_probability(
    gh: int, ga: int, lam_h: float, lam_a: float, rho: float = -0.10
) -> float:
    """Dixon-Coles corrected score probability.

    P(gh,ga) = τ(gh,ga) × Poisson(gh|λh) × Poisson(ga|λa)
    """
    raw = poisson_pmf(gh, lam_h) * poisson_pmf(ga, lam_a)
    return raw * tau(gh, ga, lam_h, lam_a, rho)


def dc_score_matrix(
    lam_h: float, lam_a: float, max_g: int = 8, rho: float = -0.10
) -> dict[str, float]:
    """Full Dixon-Coles score probability matrix."""
    dist: dict[str, float] = {}
    total = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = dc_score_probability(h, a, lam_h, lam_a, rho)
            dist[f"{h}-{a}"] = p
            total += p

    if total > 0:
        for k in dist:
            dist[k] /= total
    return dist


def dc_marginals(
    lam_h: float, lam_a: float, max_g: int = 8, rho: float = -0.10
) -> dict[str, Any]:
    """Dixon-Coles corrected H/D/A, over/under, BTTS.

    This is the primary prediction entry point.
    """
    dist = dc_score_matrix(lam_h, lam_a, max_g, rho)

    hw = dr = aw = 0.0
    over25 = over35 = btts = 0.0
    scores_list = []

    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a:
            hw += prob
        elif h == a:
            dr += prob
        else:
            aw += prob
        if h + a > 2.5:
            over25 += prob
        if h + a > 3.5:
            over35 += prob
        if h > 0 and a > 0:
            btts += prob
        scores_list.append((score, prob))

    scores_list.sort(key=lambda x: x[1], reverse=True)
    conc = sum(p * p for _, p in scores_list)

    return {
        "score_distribution": dict(scores_list),
        "home_win": round(hw, 4),
        "draw": round(dr, 4),
        "away_win": round(aw, 4),
        "over_25": round(over25, 4),
        "over_35": round(over35, 4),
        "btts": round(btts, 4),
        "top_5_scores": scores_list[:5],
        "concentration": round(conc, 4),
        "diagnostics": {
            "1-1_prob": round(dist.get("1-1", 0), 4),
            "0-0_prob": round(dist.get("0-0", 0), 4),
            "1-0_prob": round(dist.get("1-0", 0), 4),
            "0-1_prob": round(dist.get("0-1", 0), 4),
        },
        "rho": rho,
    }


def estimate_rho(
    actual_scores: list[tuple[int, int]],
    lam_h_list: list[float],
    lam_a_list: list[float],
) -> float:
    """Estimate ρ from historical data via grid search MLE.

    Args:
        actual_scores: [(home_goals, away_goals), ...]
        lam_h_list: home λ for each match
        lam_a_list: away λ for each match

    Returns:
        Optimal ρ value in [-0.15, 0.05]
    """
    best_rho = -0.10
    best_ll = float("-inf")

    for rho in [x / 100 for x in range(-15, 6, 1)]:
        ll = 0.0
        for (gh, ga), lh, la in zip(actual_scores, lam_h_list, lam_a_list):
            p = dc_score_probability(gh, ga, lh, la, rho)
            ll += math.log(max(p, 1e-10))
        if ll > best_ll:
            best_ll = ll
            best_rho = rho

    return round(best_rho, 4)


# ============================================================
# DixonColesModel — trainable, persistent model
# ============================================================

def _resolve_team_name(name: str, known_teams: dict) -> str:
    """Resolve a team name to its canonical CSV form.

    First checks exact match, then tries common alias patterns,
    then substring matching as a last resort.
    """
    if name in known_teams:
        return name

    # Common aliases (same map as data_loader)
    aliases = {
        "Borussia Dortmund": "Dortmund",
        "AC Milan": "Milan",
        "Inter Milan": "Inter",
        "Atletico Madrid": "Ath Madrid",
        "Atlético Madrid": "Ath Madrid",
        "Manchester City": "Man City",
        "Manchester United": "Man United",
        "Manchester Utd": "Man United",
        "Wolverhampton": "Wolves",
        "Wolverhampton Wanderers": "Wolves",
        "Tottenham Hotspur": "Tottenham",
        "Newcastle United": "Newcastle",
        "Newcastle Utd": "Newcastle",
        "Nottingham Forest": "Nott'm Forest",
        "Paris Saint-Germain": "Paris SG",
        "Paris Saint Germain": "Paris SG",
        "Athletic Bilbao": "Ath Bilbao",
        "Real Sociedad": "Sociedad",
        "Eintracht Frankfurt": "Ein Frankfurt",
        "Bayer Leverkusen": "Leverkusen",
        "Borussia M'gladbach": "M'gladbach",
        # 2. Bundesliga
        "Dynamo Dresden": "Dresden",
        "SG Dynamo Dresden": "Dresden",
        # Eredivisie
        "Ajax Amsterdam": "Ajax", "PSV Eindhoven": "PSV",
        "FC Utrecht": "Utrecht", "PEC Zwolle": "Zwolle",
        "FC Twente": "Twente", "SC Heerenveen": "Heerenveen",
        "FC Groningen": "Groningen",
        # Primeira Liga
        "Braga": "Sp Braga", "Sporting Braga": "Sp Braga",
        "SC Braga": "Sp Braga", "Vitoria Guimaraes": "Guimaraes",
        "Vitoria SC": "Guimaraes", "FC Porto": "Porto",
        "SL Benfica": "Benfica", "Sporting Lisbon": "Sp Lisbon",
        "Sporting CP": "Sp Lisbon",
        # Norway (openfootball)
        "Rosenborg BK": "Rosenborg", "Molde FK": "Molde",
        "Lillestrom SK": "Lillestrom", "Lillestrøm SK": "Lillestrom",
        "Hamarkameratene": "HamKam", "Aalesunds FK": "Aalesund",
        "Kristiansund BK": "Kristiansund",
        # Sweden (openfootball)
        "Hammarby IF": "Hammarby", "BK Hacken": "Hacken",
        "BK Häcken": "Hacken", "IFK Goteborg": "IFK Goteborg",
        "IFK Göteborg": "IFK Goteborg", "GAIS Goteborg": "GAIS",
        "GAIS Göteborg": "GAIS", "Kalmar FF": "Kalmar",
        "Halmstads BK": "Halmstads",
        # Finland (openfootball)
        "HJK Helsinki": "HJK", "FC Lahti": "Lahti",
        "Kuopion PS": "KuPS", "AC Oulu": "AC Oulu",
        "Inter Turku": "Inter Turku", "TPS": "TPS",
        # Brazil (openfootball)
        "Flamengo RJ": "Flamengo", "CR Flamengo": "Flamengo",
        "Santos FC": "Santos", "Athletico Paranaense": "Athletico-PR",
        "Fortaleza EC": "Fortaleza", "Sao Paulo FC": "Sao Paulo",
        # Japan J1 (openfootball)
        "Kyoto Sanga FC": "Kyoto Sanga",
    }
    if name in aliases:
        resolved = aliases[name]
        if resolved in known_teams:
            return resolved

    # No substring fallback — too many false positives
    # (e.g., "Inter" matched "Inter Turku", "Lille" matched "Lillestrom")
    return name


class DixonColesModel:
    """Fitted Dixon-Coles model with per-team attack/defense parameters.

    Usage:
        model = DixonColesModel()
        model.fit(matches)          # train on historical data
        model.save("data/state/")   # persist
        pred = model.predict("Liverpool", "Arsenal", "PL")
    """

    def __init__(self):
        self.team_attack: dict[str, float] = {}
        self.team_defense: dict[str, float] = {}
        self.team_league: dict[str, str] = {}       # team → league_code
        self.league_rho: dict[str, float] = {}
        self.league_home_adv: dict[str, float] = {}
        self.league_avg_goals: dict[str, float] = {}
        self._fitted = False
        self._league_medians_cache: dict | None = None

    # ================================================================
    # Simple fitting (analytical approach — no scipy needed initially)
    # ================================================================

    def fit_simple(self, matches: list[dict]) -> None:
        """Fit attack/defense parameters using a simplified analytical approach.

        This avoids scipy dependency for initial deployment. Uses:
        - Attack = team's avg goals scored / league avg goals
        - Defense = team's avg goals conceded / league avg goals
        - ρ estimated via grid search per league
        - Home advantage = ratio of home goals to away goals

        For a more rigorous fit, use fit_mle() which requires scipy.
        """
        # Step 1: Compute league-level statistics
        league_stats: dict[str, dict] = {}
        for m in matches:
            code = m["league_code"]
            if code not in league_stats:
                league_stats[code] = {
                    "total_goals": 0, "home_goals": 0, "away_goals": 0,
                    "n": 0, "scores": [], "lam_h": [], "lam_a": [],
                }
            s = league_stats[code]
            s["total_goals"] += m["home_goals"] + m["away_goals"]
            s["home_goals"] += m["home_goals"]
            s["away_goals"] += m["away_goals"]
            s["n"] += 1
            s["scores"].append((m["home_goals"], m["away_goals"]))

        for code, s in league_stats.items():
            s["avg_total"] = s["total_goals"] / s["n"]
            s["avg_home"] = s["home_goals"] / s["n"]
            s["avg_away"] = s["away_goals"] / s["n"]
            # Home advantage = home_goals / away_goals - 1
            if s["avg_away"] > 0:
                s["home_adv"] = s["avg_home"] / s["avg_away"] - 1
            else:
                s["home_adv"] = 0.30

        # Step 2: Compute team-level attack/defense
        team_goals_for: dict[str, list[float]] = {}
        team_goals_against: dict[str, list[float]] = {}
        team_league: dict[str, str] = {}

        for m in matches:
            code = m["league_code"]
            home = m["home_team"]
            away = m["away_team"]
            team_league[home] = code
            team_league[away] = code
            self.team_league[home] = code
            self.team_league[away] = code

            if home not in team_goals_for:
                team_goals_for[home] = []
                team_goals_against[home] = []
            if away not in team_goals_for:
                team_goals_for[away] = []
                team_goals_against[away] = []

            team_goals_for[home].append(m["home_goals"])
            team_goals_against[home].append(m["away_goals"])
            team_goals_for[away].append(m["away_goals"])
            team_goals_against[away].append(m["home_goals"])

        # Step 3: Calculate attack/defense relative to league average
        for team, goals in team_goals_for.items():
            code = team_league.get(team, "")
            ls = league_stats.get(code, {})
            league_avg = ls.get("avg_total", 2.5) / 2  # per-team avg

            avg_for = sum(goals) / len(goals) if goals else league_avg
            avg_against = sum(team_goals_against.get(team, [0])) / max(len(team_goals_against.get(team, [0])), 1)

            # Attack multiplier: team goals / league avg
            attack = avg_for / league_avg if league_avg > 0 else 1.0
            defense = avg_against / league_avg if league_avg > 0 else 1.0

            # Regularization: teams with few matches pulled toward 1.0
            n = len(goals)
            if n < 10:
                reg_weight = n / 10  # 0.1 to 1.0
                attack = 1.0 + (attack - 1.0) * reg_weight
                defense = 1.0 + (defense - 1.0) * reg_weight

            self.team_attack[team] = round(max(0.5, min(2.0, attack)), 4)
            self.team_defense[team] = round(max(0.5, min(2.0, defense)), 4)

        # Step 4: Estimate ρ per league via grid search
        for code, s in league_stats.items():
            league_avg = s["avg_total"]
            # Use league average as baseline λ for ρ estimation
            avg_lam = league_avg / 2
            lam_h_list = [avg_lam * (1 + s.get("home_adv", 0.30) / 2)] * len(s["scores"])
            lam_a_list = [avg_lam] * len(s["scores"])
            if s["scores"]:
                self.league_rho[code] = estimate_rho(
                    s["scores"], lam_h_list, lam_a_list
                )
            else:
                self.league_rho[code] = -0.10

        # Step 5: Store league parameters
        for code, s in league_stats.items():
            self.league_home_adv[code] = round(s.get("home_adv", 0.30), 4)
            self.league_avg_goals[code] = round(s["avg_total"], 2)

        self._fitted = True

    def fit_mle(self, matches: list[dict]) -> None:
        """Maximum likelihood estimation using scipy L-BFGS-B.

        Jointly estimates:
        - attack[t] for each team (constrained > 0, mean ≈ 1)
        - defense[t] for each team
        - ρ[L] for each league
        - home_adv[L] for each league

        Vectorized: all 26,663 matches evaluated in one numpy call.
        Requires: scipy, numpy
        Falls back to fit_simple() if scipy is unavailable.
        """
        try:
            import numpy as np
            from scipy.optimize import minimize
            from scipy.special import gammaln
        except ImportError:
            print("scipy not available, falling back to fit_simple()")
            self.fit_simple(matches)
            return

        # ── Build team & league indices ──
        teams = set()
        leagues = set()
        for m in matches:
            teams.add(m["home_team"])
            teams.add(m["away_team"])
            leagues.add(m["league_code"])

        team_list = sorted(teams)
        league_list = sorted(leagues)
        team_idx = {t: i for i, t in enumerate(team_list)}
        league_idx = {l: i for i, l in enumerate(league_list)}

        n_teams = len(team_list)
        n_leagues = len(league_list)

        # ── Warm-start from analytical fit ──
        if not self._fitted:
            self.fit_simple(matches)

        # ── Pre-compute per-match numpy arrays (all vectorized) ──
        n_matches = len(matches)
        m_gh = np.array([m["home_goals"] for m in matches], dtype=np.int32)
        m_ga = np.array([m["away_goals"] for m in matches], dtype=np.int32)
        m_home_idx = np.array([team_idx[m["home_team"]] for m in matches], dtype=np.int32)
        m_away_idx = np.array([team_idx[m["away_team"]] for m in matches], dtype=np.int32)
        m_league_idx = np.array([league_idx[m["league_code"]] for m in matches], dtype=np.int32)

        # Per-match league average goals
        league_goals = {}
        for l in league_list:
            lm = [m for m in matches if m["league_code"] == l]
            tg = sum(m["home_goals"] + m["away_goals"] for m in lm)
            league_goals[l] = tg / len(lm) if lm else 2.5
        league_avg_arr = np.array([league_goals[lg] for lg in league_list])
        m_avg_g = league_avg_arr[m_league_idx]  # shape (n_matches,)

        # Pre-compute log(k!) via gammaln(k+1) — numerically stable
        m_log_fact_gh = gammaln(m_gh + 1)
        m_log_fact_ga = gammaln(m_ga + 1)

        # Boolean masks for τ-correction scores (only 4 scorelines affected)
        mask_00 = (m_gh == 0) & (m_ga == 0)
        mask_10 = (m_gh == 1) & (m_ga == 0)
        mask_01 = (m_gh == 0) & (m_ga == 1)
        mask_11 = (m_gh == 1) & (m_ga == 1)

        # ── Initial parameter vector ──
        x0 = []
        for t in team_list:
            x0.append(self.team_attack.get(t, 1.0))
        for t in team_list:
            x0.append(self.team_defense.get(t, 1.0))
        for l in league_list:
            x0.append(self.league_rho.get(l, -0.10))
        for l in league_list:
            x0.append(self.league_home_adv.get(l, 0.30))
        x0 = np.array(x0, dtype=np.float64)

        # ── Vectorized NLL + analytical gradient (returns (f, g) tuple) ──
        def nll_and_grad(x):
            att = x[:n_teams]
            def_ = x[n_teams : 2 * n_teams]
            rho = x[2 * n_teams : 2 * n_teams + n_leagues]
            ha = x[2 * n_teams + n_leagues :]

            # --- Expected goals (fully vectorized) ---
            lam_h = (m_avg_g / 2.0) * att[m_home_idx] * def_[m_away_idx] * (1.0 + ha[m_league_idx])
            lam_a = (m_avg_g / 2.0) * att[m_away_idx] * def_[m_home_idx]
            lam_h = np.maximum(lam_h, 1e-8)
            lam_a = np.maximum(lam_a, 1e-8)

            # --- Log-Poisson ---
            log_p_h = m_gh * np.log(lam_h) - lam_h - m_log_fact_gh
            log_p_a = m_ga * np.log(lam_a) - lam_a - m_log_fact_ga

            # --- τ correction ---
            rho_m = rho[m_league_idx]
            tau_val = np.ones(n_matches, dtype=np.float64)
            tau_val[mask_00] = np.maximum(0.0, 1.0 - lam_h[mask_00] * lam_a[mask_00] * rho_m[mask_00])
            tau_val[mask_10] = np.maximum(0.0, 1.0 + lam_h[mask_10] * rho_m[mask_10])
            tau_val[mask_01] = np.maximum(0.0, 1.0 + lam_a[mask_01] * rho_m[mask_01])
            tau_val[mask_11] = np.maximum(0.0, 1.0 - rho_m[mask_11])
            log_tau = np.log(np.maximum(tau_val, 1e-12))

            # --- NLL value ---
            ll = np.sum(log_tau + log_p_h + log_p_a)
            reg = 0.01 * (np.sum((att - 1.0) ** 2) + np.sum((def_ - 1.0) ** 2))
            nll = float(-(ll - reg))

            # ============================================================
            # Analytical gradient (fully vectorized)
            # ============================================================

            # τ log-derivatives: d(log τ)/dλh, d(log τ)/dλa, d(log τ)/dρ
            # Use safe_tau to avoid divide-by-zero (τ clamped to ≥0 for max, may be 0)
            safe_tau = np.maximum(tau_val, 1e-12)
            dlogtau_dlamh = np.zeros(n_matches)
            dlogtau_dlama = np.zeros(n_matches)
            dlogtau_drho   = np.zeros(n_matches)

            # 0-0: τ = 1 - λh·λa·ρ
            dlogtau_dlamh[mask_00] = (-lam_a[mask_00] * rho_m[mask_00]) / safe_tau[mask_00]
            dlogtau_dlama[mask_00] = (-lam_h[mask_00] * rho_m[mask_00]) / safe_tau[mask_00]
            dlogtau_drho[mask_00]   = (-lam_h[mask_00] * lam_a[mask_00]) / safe_tau[mask_00]
            # 1-0: τ = 1 + λh·ρ
            dlogtau_dlamh[mask_10] = rho_m[mask_10] / safe_tau[mask_10]
            dlogtau_drho[mask_10]   = lam_h[mask_10] / safe_tau[mask_10]
            # 0-1: τ = 1 + λa·ρ
            dlogtau_dlama[mask_01] = rho_m[mask_01] / safe_tau[mask_01]
            dlogtau_drho[mask_01]   = lam_a[mask_01] / safe_tau[mask_01]
            # 1-1: τ = 1 - ρ
            dlogtau_drho[mask_11]   = -1.0 / safe_tau[mask_11]

            # Per-match contribution: τ'_λh * λh + gh - λh  (goes to home-team attack / away-team defense)
            contrib_h = dlogtau_dlamh * lam_h + m_gh - lam_h
            # Per-match contribution: τ'_λa * λa + ga - λa  (goes to away-team attack / home-team defense)
            contrib_a = dlogtau_dlama * lam_a + m_ga - lam_a

            # --- Grad: attack[t] ---
            # LL contribution from matches where t is home + where t is away
            grad_att_raw = np.bincount(m_home_idx, weights=contrib_h, minlength=n_teams)
            grad_att_raw += np.bincount(m_away_idx, weights=contrib_a, minlength=n_teams)
            # ∂NLL/∂att = -(∂LL/∂att) + 0.02*(att - 1)
            grad_att = -np.divide(grad_att_raw, att, where=att > 1e-10, out=np.zeros_like(grad_att_raw)) + 0.02 * (att - 1.0)

            # --- Grad: defense[t] ---
            # contrib_h (when team is home): opponent defense (= away team) gets gradient
            # contrib_a (when team is away): opponent defense (= home team) gets gradient
            grad_def_raw = np.bincount(m_away_idx, weights=contrib_h, minlength=n_teams)
            grad_def_raw += np.bincount(m_home_idx, weights=contrib_a, minlength=n_teams)
            grad_def = -np.divide(grad_def_raw, def_, where=def_ > 1e-10, out=np.zeros_like(grad_def_raw)) + 0.02 * (def_ - 1.0)

            # --- Grad: rho[L] ---
            grad_rho = -np.bincount(m_league_idx, weights=dlogtau_drho, minlength=n_leagues)

            # --- Grad: home_adv[L] ---
            # ∂λh/∂ha = λh/(1+ha), so ∂ll/∂ha = contrib_h / (1+ha)
            one_plus_ha = 1.0 + ha[m_league_idx]
            grad_ha_raw = np.bincount(m_league_idx,
                                       weights=contrib_h / np.maximum(one_plus_ha, 1e-8),
                                       minlength=n_leagues)
            grad_ha = -grad_ha_raw  # no L2 reg on home_adv

            # --- Assemble full gradient vector ---
            grad = np.concatenate([grad_att, grad_def, grad_rho, grad_ha])

            return nll, grad

        # ── Optimize (with analytical gradient) ──
        print(f"  MLE: {n_teams} teams, {n_leagues} leagues, {n_matches} matches")
        print(f"  Parameters: {len(x0)} ({n_teams}att + {n_teams}def + {n_leagues}rho + {n_leagues}ha)")

        result = minimize(
            nll_and_grad, x0,
            method="L-BFGS-B",
            jac=True,  # objective returns (f, g) tuple
            bounds=(
                [(0.3, 3.0)] * n_teams +            # attack
                [(0.3, 3.0)] * n_teams +            # defense
                [(-0.20, 0.10)] * n_leagues +       # rho
                [(0.0, 0.60)] * n_leagues            # home_adv
            ),
            options={"maxiter": 500},  # ftol default ≈1e-7 is fine; we use analytical grad
        )

        if not result.success:
            print(f"  [WARN] Optimizer: {result.message}")

        # ── Unpack result ──
        att = result.x[:n_teams]
        def_ = result.x[n_teams : 2 * n_teams]
        rho_arr = result.x[2 * n_teams : 2 * n_teams + n_leagues]
        ha_arr = result.x[2 * n_teams + n_leagues :]

        for i, t in enumerate(team_list):
            self.team_attack[t] = round(float(att[i]), 4)
            self.team_defense[t] = round(float(def_[i]), 4)
        # Store team→league mapping from match data
        for m in matches:
            self.team_league[m["home_team"]] = m["league_code"]
            self.team_league[m["away_team"]] = m["league_code"]
        for i, l in enumerate(league_list):
            self.league_rho[l] = round(float(rho_arr[i]), 4)
            self.league_home_adv[l] = round(float(ha_arr[i]), 4)
        for l in league_list:
            self.league_avg_goals[l] = round(league_goals[l], 2)

        print(f"  MLE converged: {result.message} | nit={result.nit} | final NLL={result.fun:.2f}")
        self._fitted = True

    # ================================================================
    # League-median fallback for cold start teams
    # ================================================================

    def _get_league_medians(self) -> dict[str, dict[str, float]]:
        """Compute per-league median attack/defense from known teams.

        Used as fallback for cold-start teams instead of blind 1.0.
        Cached on first call.
        """
        if self._league_medians_cache is not None:
            return self._league_medians_cache

        from collections import defaultdict
        league_att: dict[str, list[float]] = defaultdict(list)
        league_def: dict[str, list[float]] = defaultdict(list)

        for team, att in self.team_attack.items():
            lg = self.team_league.get(team, "")
            if lg:
                league_att[lg].append(att)
                league_def[lg].append(self.team_defense.get(team, 1.0))

        self._league_medians_cache = {}
        for code in self.league_avg_goals:
            atts = sorted(league_att.get(code, [1.0]))
            defs = sorted(league_def.get(code, [1.0]))
            if atts:
                self._league_medians_cache[code] = {
                    "att": round(atts[len(atts)//2], 4),
                    "def": round(defs[len(defs)//2], 4),
                }
            else:
                self._league_medians_cache[code] = {"att": 1.0, "def": 1.0}

        return self._league_medians_cache

    # ================================================================
    # Prediction
    # ================================================================

    def predict(
        self,
        home_team: str,
        away_team: str,
        league_code: str,
        max_g: int = 8,
        form_factors: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Predict match outcome probabilities.

        Args:
            home_team: home team name
            away_team: away team name
            league_code: league identifier (e.g., "PL", "BL1")
            form_factors: optional {team: {attack_form, defense_form}}
                from compute_form_factors(). When provided, recent form adjusts
                the long-term attack/defense parameters multiplicatively.

        Returns:
            Full prediction dict with H/D/A, over/under, BTTS, top scores
        """
        # Resolve team name aliases
        home_resolved = _resolve_team_name(home_team, self.team_attack)
        away_resolved = _resolve_team_name(away_team, self.team_attack)

        # Get team parameters (default to league-median, not blind 1.0)
        att_h = self.team_attack.get(home_resolved, 1.0)
        def_h = self.team_defense.get(home_resolved, 1.0)
        att_a = self.team_attack.get(away_resolved, 1.0)
        def_a = self.team_defense.get(away_resolved, 1.0)

        # Cold start detection
        home_cold = home_resolved not in self.team_attack
        away_cold = away_resolved not in self.team_attack

        # Use league-median fallback for unknown teams
        if home_cold or away_cold:
            league_medians = self._get_league_medians()
            # Find which league(s) these teams belong to (use current match's league as proxy)
            med = league_medians.get(league_code, {"att": 1.0, "def": 1.0})
            if home_cold:
                att_h = med["att"]
                def_h = med["def"]
            if away_cold:
                att_a = med["att"]
                def_a = med["def"]

        # Get league parameters
        avg_goals = self.league_avg_goals.get(league_code, 2.65)
        home_adv = self.league_home_adv.get(league_code, 0.30)
        rho = self.league_rho.get(league_code, -0.10)

        # Compute expected goals
        lam_h = (avg_goals / 2) * att_h * def_a * (1 + home_adv)
        lam_a = (avg_goals / 2) * att_a * def_h

        # ── Apply recent form factors if available ──
        form_h = None
        form_a = None
        if form_factors:
            hf = form_factors.get(home_resolved) or form_factors.get(home_team, {})
            af = form_factors.get(away_resolved) or form_factors.get(away_team, {})
            if hf or af:
                f_att_h = hf.get("attack_form", 1.0)
                f_def_h = hf.get("defense_form", 1.0)
                f_att_a = af.get("attack_form", 1.0)
                f_def_a = af.get("defense_form", 1.0)

                # Blend: λ = (1-w)*λ_base + w*λ_form
                # 25% form signal — enough to matter, not enough to dominate
                FORM_BLEND = 0.25
                lam_h_form = lam_h * f_att_h * f_def_a
                lam_a_form = lam_a * f_att_a * f_def_h
                lam_h = (1 - FORM_BLEND) * lam_h + FORM_BLEND * lam_h_form
                lam_a = (1 - FORM_BLEND) * lam_a + FORM_BLEND * lam_a_form

                form_h = hf
                form_a = af

        # Get Dixon-Coles marginals
        result = dc_marginals(lam_h, lam_a, max_g, rho)

        # Add metadata
        result["lambda_home"] = round(lam_h, 4)
        result["lambda_away"] = round(lam_a, 4)
        result["home_attack"] = att_h
        result["home_defense"] = def_h
        result["away_attack"] = att_a
        result["away_defense"] = def_a
        result["cold_start"] = home_cold or away_cold
        result["cold_start_detail"] = {
            "home_cold": home_cold,
            "away_cold": away_cold,
            "home_fallback_att": att_h if home_cold else None,
            "away_fallback_att": att_a if away_cold else None,
        }
        if form_h:
            result["home_form"] = form_h
        if form_a:
            result["away_form"] = form_a

        return result

    # ================================================================
    # Persistence
    # ================================================================

    def save(self, dir_path: str) -> None:
        """Save model parameters to JSON files."""
        os.makedirs(dir_path, exist_ok=True)

        team_params = {}
        for team in self.team_attack:
            team_params[team] = {
                "attack": self.team_attack[team],
                "defense": self.team_defense[team],
            }

        with open(os.path.join(dir_path, "team_params.json"), "w", encoding="utf-8") as f:
            json.dump(team_params, f, ensure_ascii=False, indent=2)

        league_params = {}
        for code in self.league_rho:
            league_params[code] = {
                "rho": self.league_rho[code],
                "home_adv": self.league_home_adv.get(code, 0.30),
                "avg_goals": self.league_avg_goals.get(code, 2.65),
            }

        # Save team→league mapping
        with open(os.path.join(dir_path, "team_league.json"), "w", encoding="utf-8") as f:
            json.dump(self.team_league, f, ensure_ascii=False, indent=2)

        with open(os.path.join(dir_path, "league_params.json"), "w", encoding="utf-8") as f:
            json.dump(league_params, f, ensure_ascii=False, indent=2)

    def load(self, dir_path: str) -> bool:
        """Load model parameters from JSON files."""
        team_path = os.path.join(dir_path, "team_params.json")
        league_path = os.path.join(dir_path, "league_params.json")
        team_league_path = os.path.join(dir_path, "team_league.json")

        if not os.path.exists(team_path):
            return False

        with open(team_path, "r", encoding="utf-8") as f:
            team_data = json.load(f)
        for team, params in team_data.items():
            self.team_attack[team] = params["attack"]
            self.team_defense[team] = params["defense"]

        if os.path.exists(league_path):
            with open(league_path, "r", encoding="utf-8") as f:
                league_data = json.load(f)
            for code, params in league_data.items():
                self.league_rho[code] = params["rho"]
                self.league_home_adv[code] = params.get("home_adv", 0.30)
                self.league_avg_goals[code] = params.get("avg_goals", 2.65)

        if os.path.exists(team_league_path):
            with open(team_league_path, "r", encoding="utf-8") as f:
                self.team_league = json.load(f)

        self._league_medians_cache = None  # reset cache on load
        self._fitted = True
        return True

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def team_count(self) -> int:
        return len(self.team_attack)
