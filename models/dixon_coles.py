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
        self.league_rho: dict[str, float] = {}
        self.league_home_adv: dict[str, float] = {}
        self.league_avg_goals: dict[str, float] = {}
        self._fitted = False

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
        """Maximum likelihood estimation using scipy BFGS.

        Jointly estimates:
        - attack[t] for each team (constrained > 0, mean = 1)
        - defense[t] for each team
        - ρ[L] for each league
        - home_adv[L] for each league

        Requires: scipy
        Falls back to fit_simple() if scipy is unavailable.
        """
        try:
            import numpy as np
            from scipy.optimize import minimize
        except ImportError:
            print("scipy not available, falling back to fit_simple()")
            self.fit_simple(matches)
            return

        # Build team and league indices
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

        # Initialize from simple fit
        if not self._fitted:
            self.fit_simple(matches)

        # Initial parameters: attack (n_teams), defense (n_teams), rho (n_leagues), home_adv (n_leagues)
        x0 = []
        for t in team_list:
            x0.append(self.team_attack.get(t, 1.0))
        for t in team_list:
            x0.append(self.team_defense.get(t, 1.0))
        for l in league_list:
            x0.append(self.league_rho.get(l, -0.10))
        for l in league_list:
            x0.append(self.league_home_adv.get(l, 0.30))

        x0 = np.array(x0)

        # Pre-compute league stats
        league_goals = {}
        for l in league_list:
            league_matches = [m for m in matches if m["league_code"] == l]
            total_g = sum(m["home_goals"] + m["away_goals"] for m in league_matches)
            league_goals[l] = total_g / len(league_matches) if league_matches else 2.5

        # Build match index arrays
        m_home_idx = np.array([team_idx[m["home_team"]] for m in matches])
        m_away_idx = np.array([team_idx[m["away_team"]] for m in matches])
        m_league_idx = np.array([league_idx[m["league_code"]] for m in matches])
        m_gh = np.array([m["home_goals"] for m in matches])
        m_ga = np.array([m["away_goals"] for m in matches])

        def unpack(x):
            att = x[:n_teams]
            def_ = x[n_teams : 2 * n_teams]
            rho = x[2 * n_teams : 2 * n_teams + n_leagues]
            ha = x[2 * n_teams + n_leagues :]
            return att, def_, rho, ha

        def neg_log_likelihood(x):
            att, def_, rho, ha = unpack(x)
            ll = 0.0
            for i in range(len(matches)):
                l_idx = m_league_idx[i]
                lg = league_list[l_idx]
                avg_g = league_goals[lg]

                lam_h = (avg_g / 2) * att[m_home_idx[i]] * def_[m_away_idx[i]] * (1 + ha[l_idx])
                lam_a = (avg_g / 2) * att[m_away_idx[i]] * def_[m_home_idx[i]]

                p = dc_score_probability(
                    int(m_gh[i]), int(m_ga[i]), lam_h, lam_a, rho[l_idx]
                )
                ll += math.log(max(p, 1e-10))

            # L2 regularization: attack/defense pulled toward 1.0
            reg = 0.0
            for i in range(n_teams):
                reg += 0.01 * ((att[i] - 1.0) ** 2 + (def_[i] - 1.0) ** 2)
            return -(ll - reg)

        # Optimize
        result = minimize(
            neg_log_likelihood, x0,
            method="L-BFGS-B",
            bounds=(
                [(0.3, 3.0)] * n_teams +           # attack
                [(0.3, 3.0)] * n_teams +           # defense
                [(-0.20, 0.10)] * n_leagues +      # rho
                [(0.0, 0.60)] * n_leagues           # home_adv
            ),
            options={"maxiter": 500},
        )

        # Unpack result
        att, def_, rho_arr, ha_arr = unpack(result.x)
        for i, t in enumerate(team_list):
            self.team_attack[t] = round(float(att[i]), 4)
            self.team_defense[t] = round(float(def_[i]), 4)
        for i, l in enumerate(league_list):
            self.league_rho[l] = round(float(rho_arr[i]), 4)
            self.league_home_adv[l] = round(float(ha_arr[i]), 4)
        for l in league_list:
            self.league_avg_goals[l] = round(league_goals[l], 2)

        self._fitted = True

    # ================================================================
    # Prediction
    # ================================================================

    def predict(
        self,
        home_team: str,
        away_team: str,
        league_code: str,
        max_g: int = 8,
    ) -> dict[str, Any]:
        """Predict match outcome probabilities.

        Args:
            home_team: home team name
            away_team: away team name
            league_code: league identifier (e.g., "PL", "BL1")

        Returns:
            Full prediction dict with H/D/A, over/under, BTTS, top scores
        """
        # Resolve team name aliases
        home_resolved = _resolve_team_name(home_team, self.team_attack)
        away_resolved = _resolve_team_name(away_team, self.team_attack)

        # Get team parameters (default to neutral 1.0)
        att_h = self.team_attack.get(home_resolved, 1.0)
        def_h = self.team_defense.get(home_resolved, 1.0)
        att_a = self.team_attack.get(away_resolved, 1.0)
        def_a = self.team_defense.get(away_resolved, 1.0)

        # Get league parameters
        avg_goals = self.league_avg_goals.get(league_code, 2.65)
        home_adv = self.league_home_adv.get(league_code, 0.30)
        rho = self.league_rho.get(league_code, -0.10)

        # Compute expected goals
        lam_h = (avg_goals / 2) * att_h * def_a * (1 + home_adv)
        lam_a = (avg_goals / 2) * att_a * def_h

        # Get Dixon-Coles marginals
        result = dc_marginals(lam_h, lam_a, max_g, rho)

        # Add metadata
        result["lambda_home"] = round(lam_h, 4)
        result["lambda_away"] = round(lam_a, 4)
        result["home_attack"] = att_h
        result["home_defense"] = def_h
        result["away_attack"] = att_a
        result["away_defense"] = def_a
        result["cold_start"] = (
            home_resolved not in self.team_attack or away_resolved not in self.team_attack
        )

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

        with open(os.path.join(dir_path, "league_params.json"), "w", encoding="utf-8") as f:
            json.dump(league_params, f, ensure_ascii=False, indent=2)

    def load(self, dir_path: str) -> bool:
        """Load model parameters from JSON files."""
        team_path = os.path.join(dir_path, "team_params.json")
        league_path = os.path.join(dir_path, "league_params.json")

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

        self._fitted = True
        return True

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def team_count(self) -> int:
        return len(self.team_attack)
