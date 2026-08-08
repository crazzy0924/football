"""
ELO Rating System v3.0

Persistent ELO ratings trained from historical match data.
Reads/writes JSON state. No hardcoded team list — learns from data.

Core math preserved from v2.0:
- expected_result: standard ELO formula with 400-point basis
- update: K-factor × goal-diff-multiplier × (actual - expected)
- win_probability: ELO-diff → H/D/A probabilities via exponential draw decay
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


class EloSystem:
    """Persistent ELO rating system for football teams.

    Usage:
        elo = EloSystem()
        elo.initialize_from_matches(matches)   # train from historical data
        elo.save("data/state/elo_ratings.json") # persist

        # Predict
        probs = elo.win_probability("Liverpool", "Arsenal", home=True)
    """

    DEFAULT_ELO = 1500.0
    K_FACTOR = 32.0
    GOAL_DIFF_INDEX = 0.8

    def __init__(self, state_path: str = "data/state/elo_ratings.json"):
        self._ratings: dict[str, float] = {}
        self._match_count: dict[str, int] = {}
        self._state_path = state_path
        self._league_home_advantage: dict[str, float] = {}
        self._league_base_elo: dict[str, float] = {}

    # ================================================================
    # Persistence
    # ================================================================

    def load(self, path: str | None = None) -> bool:
        """Load ratings from JSON. Returns True if file existed."""
        p = path or self._state_path
        if not os.path.exists(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._ratings = data.get("ratings", {})
        self._match_count = data.get("match_count", {})
        self._league_home_advantage = data.get("league_home_advantage", {})
        self._league_base_elo = data.get("league_base_elo", {})
        return True

    def save(self, path: str | None = None) -> None:
        """Save ratings to JSON."""
        p = path or self._state_path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = {
            "ratings": self._ratings,
            "match_count": self._match_count,
            "league_home_advantage": self._league_home_advantage,
            "league_base_elo": self._league_base_elo,
            "team_count": len(self._ratings),
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ================================================================
    # Training: chronological replay from match list
    # ================================================================

    def initialize_from_matches(
        self,
        matches: list[dict],
        league_profiles: dict[str, Any] | None = None,
    ) -> None:
        """Chronologically replay all matches to converge ELO ratings.

        Args:
            matches: sorted by date. Each dict must have:
                home_team, away_team, home_goals, away_goals, league_code
            league_profiles: optional dict of league_code -> LeagueProfile
        """
        # Set league-specific home advantages from profiles
        if league_profiles:
            for code, prof in league_profiles.items():
                ha = getattr(prof, "home_advantage_elo", None)
                if ha is not None:
                    self._league_home_advantage[code] = ha
                base = getattr(prof, "elo_base", None)
                if base is not None:
                    self._league_base_elo[code] = base

        for m in matches:
            home = m["home_team"]
            away = m["away_team"]
            gh = m["home_goals"]
            ga = m["away_goals"]
            league = m.get("league_code", "")

            # Ensure ratings exist
            if home not in self._ratings:
                self._ratings[home] = self._get_initial_elo(league)
            if away not in self._ratings:
                self._ratings[away] = self._get_initial_elo(league)

            # Update ELO
            home_elo = self._ratings[home]
            away_elo = self._ratings[away]
            ha_bonus = self._league_home_advantage.get(league, 100)

            new_home, new_away = self._update_match(
                home_elo, away_elo, gh, ga, ha_bonus
            )
            self._ratings[home] = new_home
            self._ratings[away] = new_away
            self._match_count[home] = self._match_count.get(home, 0) + 1
            self._match_count[away] = self._match_count.get(away, 0) + 1

    def _get_initial_elo(self, league_code: str) -> float:
        """Get initial ELO for a new team based on league baseline."""
        return self._league_base_elo.get(league_code, self.DEFAULT_ELO)

    def _update_match(
        self,
        elo_home: float,
        elo_away: float,
        goals_home: int,
        goals_away: int,
        home_advantage: float,
    ) -> tuple[float, float]:
        """Update ELO for a single match result."""
        expected_home = self._expected_result(elo_home, elo_away, home_advantage)

        if goals_home > goals_away:
            actual = 1.0
        elif goals_home == goals_away:
            actual = 0.5
        else:
            actual = 0.0

        goal_diff = abs(goals_home - goals_away)
        if goal_diff <= 1:
            k_mult = 1.0
        elif goal_diff == 2:
            k_mult = 1.5
        else:
            k_mult = (11 + goal_diff) / 8.0

        k = self.K_FACTOR * k_mult
        delta = k * (actual - expected_home)
        return round(elo_home + delta, 1), round(elo_away - delta, 1)

    # ================================================================
    # Core ELO math
    # ================================================================

    @staticmethod
    def _expected_result(elo_a: float, elo_b: float, home_bonus: float = 0) -> float:
        """Expected win probability for team A (0~1)."""
        return 1.0 / (1.0 + 10 ** ((elo_b - (elo_a + home_bonus)) / 400.0))

    def get_elo(self, team_name: str, league_code: str = "") -> float:
        """Get ELO rating, falling back to league default or 1500."""
        if team_name in self._ratings:
            return self._ratings[team_name]
        return self._league_base_elo.get(league_code, self.DEFAULT_ELO)

    def get_match_count(self, team_name: str) -> int:
        """How many matches this team has in training data."""
        return self._match_count.get(team_name, 0)

    def win_probability(
        self,
        team_a: str,
        team_b: str,
        league_code: str = "",
        home_a: bool = True,
    ) -> dict[str, float]:
        """Compute H/D/A probabilities from ELO difference.

        Uses exponential draw decay: draw_prob = 0.26 × exp(-|diff| / 400)
        """
        elo_a = self.get_elo(team_a, league_code)
        elo_b = self.get_elo(team_b, league_code)
        ha = self._league_home_advantage.get(league_code, 100)

        if home_a:
            exp_home = self._expected_result(elo_a, elo_b, ha)
        else:
            exp_home = self._expected_result(elo_a, elo_b, 0)
        exp_away = 1.0 - exp_home

        elo_diff = abs(elo_a - elo_b)
        draw_prob = 0.26 * math.exp(-elo_diff / 400.0)

        total = exp_home + exp_away
        home_win = exp_home - draw_prob * exp_home / total if total > 0 else exp_home
        away_win = exp_away - draw_prob * exp_away / total if total > 0 else exp_away

        home_win = max(home_win, 0.0)
        away_win = max(away_win, 0.0)
        total = home_win + draw_prob + away_win
        if total > 0:
            home_win /= total
            draw_prob /= total
            away_win /= total

        return {
            "home_win": round(home_win, 4),
            "draw": round(draw_prob, 4),
            "away_win": round(away_win, 4),
        }

    @property
    def team_count(self) -> int:
        return len(self._ratings)

    @property
    def ratings_summary(self) -> dict[str, Any]:
        """Quick summary of the ELO database."""
        if not self._ratings:
            return {"teams": 0}
        sorted_teams = sorted(self._ratings.items(), key=lambda x: x[1], reverse=True)
        return {
            "teams": len(self._ratings),
            "top_10": [(t, r) for t, r in sorted_teams[:10]],
            "bottom_10": [(t, r) for t, r in sorted_teams[-10:]],
            "mean": round(sum(self._ratings.values()) / len(self._ratings), 1),
            "min": min(self._ratings.values()),
            "max": max(self._ratings.values()),
        }
