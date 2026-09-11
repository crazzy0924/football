"""
League Profile Database v3.0

FIXED: removed duplicate BL1 and PD keys.
ADDED: compute_league_profiles_from_matches() for data-driven profiles.

Each profile captures league-specific characteristics:
- Goal rates, win/draw/loss distribution
- Home advantage magnitude
- Market tendencies (over/under, BTTS)

These serve as priors when team-specific data is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LeagueProfile:
    """Statistical profile for a football league."""
    name: str
    code: str
    region: str = "europe"

    # Goal characteristics
    avg_home_goals: float = 1.50
    avg_away_goals: float = 1.15
    avg_total_goals: float = 2.65

    # Win/draw/loss distribution
    home_win_rate: float = 0.45
    draw_rate: float = 0.25
    away_win_rate: float = 0.30

    # Home advantage
    home_advantage_elo: float = 100
    home_goal_boost: float = 0.30

    # Market features
    over_25_rate: float = 0.50
    btts_rate: float = 0.52
    avg_corners: float = 9.8
    corner_home_share: float = 0.55

    # ELO calibration
    elo_base: float = 1500
    elo_spread: float = 200

    # Metadata
    style: str = ""
    notes: str = ""
    multi_season: list[dict] = field(default_factory=list)

    @property
    def season_count(self) -> int:
        return len(self.multi_season)


# ============================================================
# 硬编码兜底表 (2026-09-11 起仅作 fallback)
# 真正生效的是 data/state/league_profiles.json —— 由 tools/build_league_profiles.py
# 从历史 CSV 实测生成。手写表的问题: 数值陈旧(意甲主场写成 0.30, 实测 0.149),
# 且**没有 UCL 条目** → get_profile("UCL") 会落到通用默认, 与"欧冠有欧冠的特点"冲突。
# ============================================================

_HARDCODED: dict[str, LeagueProfile] = {
    # ---- Big 5 European Leagues ----
    "PL": LeagueProfile(
        name="Premier League", code="PL", region="europe",
        avg_home_goals=1.62, avg_away_goals=1.22, avg_total_goals=2.84,
        home_win_rate=0.44, draw_rate=0.23, away_win_rate=0.33,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.55, btts_rate=0.54, avg_corners=10.3,
        elo_base=1600, elo_spread=250,
        style="high_intensity",
    ),
    "PD": LeagueProfile(
        name="La Liga", code="PD", region="europe",
        avg_home_goals=1.48, avg_away_goals=1.05, avg_total_goals=2.53,
        home_win_rate=0.47, draw_rate=0.25, away_win_rate=0.28,
        home_advantage_elo=100, home_goal_boost=0.35,
        over_25_rate=0.49, btts_rate=0.49, avg_corners=9.3,
        elo_base=1580, elo_spread=280,
        style="technical",
        multi_season=[
            {"season": "21-22", "home_win": 0.46, "draw": 0.26, "away_win": 0.28, "goals": 2.50},
            {"season": "22-23", "home_win": 0.47, "draw": 0.25, "away_win": 0.28, "goals": 2.55},
            {"season": "23-24", "home_win": 0.47, "draw": 0.26, "away_win": 0.27, "goals": 2.52},
            {"season": "24-25", "home_win": 0.46, "draw": 0.25, "away_win": 0.29, "goals": 2.58},
        ],
    ),
    "BL1": LeagueProfile(
        name="Bundesliga", code="BL1", region="europe",
        avg_home_goals=1.72, avg_away_goals=1.32, avg_total_goals=3.04,
        home_win_rate=0.44, draw_rate=0.22, away_win_rate=0.34,
        home_advantage_elo=85, home_goal_boost=0.25,
        over_25_rate=0.58, btts_rate=0.56, avg_corners=10.0,
        elo_base=1560, elo_spread=220,
        style="high_scoring",
        multi_season=[
            {"season": "21-22", "home_win": 0.43, "draw": 0.23, "away_win": 0.34, "goals": 2.98},
            {"season": "22-23", "home_win": 0.44, "draw": 0.22, "away_win": 0.34, "goals": 3.12},
            {"season": "23-24", "home_win": 0.45, "draw": 0.21, "away_win": 0.34, "goals": 3.18},
            {"season": "24-25", "home_win": 0.44, "draw": 0.22, "away_win": 0.34, "goals": 3.05},
        ],
    ),
    "SA": LeagueProfile(
        name="Serie A", code="SA", region="europe",
        avg_home_goals=1.42, avg_away_goals=1.02, avg_total_goals=2.44,
        home_win_rate=0.42, draw_rate=0.28, away_win_rate=0.30,
        home_advantage_elo=95, home_goal_boost=0.30,
        over_25_rate=0.46, btts_rate=0.47, avg_corners=9.5,
        elo_base=1550, elo_spread=200,
        style="defensive",
        multi_season=[
            {"season": "21-22", "home_win": 0.41, "draw": 0.29, "away_win": 0.30, "goals": 2.58},
            {"season": "22-23", "home_win": 0.43, "draw": 0.26, "away_win": 0.31, "goals": 2.48},
            {"season": "23-24", "home_win": 0.42, "draw": 0.28, "away_win": 0.30, "goals": 2.40},
            {"season": "24-25", "home_win": 0.42, "draw": 0.28, "away_win": 0.30, "goals": 2.50},
        ],
    ),
    "FL1": LeagueProfile(
        name="Ligue 1", code="FL1", region="europe",
        avg_home_goals=1.52, avg_away_goals=1.18, avg_total_goals=2.70,
        home_win_rate=0.43, draw_rate=0.27, away_win_rate=0.30,
        home_advantage_elo=95, home_goal_boost=0.30,
        over_25_rate=0.51, btts_rate=0.51, avg_corners=9.0,
        elo_base=1520, elo_spread=250,
        style="physical",
    ),
}


def _load_data_profiles() -> dict[str, LeagueProfile]:
    """从 data/state/league_profiles.json 载入实测画像 (tools/build_league_profiles.py 生成)。"""
    import json as _json
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    p = _os.path.join(root, 'data', 'state', 'league_profiles.json')
    out: dict[str, LeagueProfile] = {}
    try:
        with open(p, encoding='utf-8') as fh:
            doc = _json.load(fh)
    except Exception:
        return out
    for code, d in doc.items():
        try:
            out[code] = LeagueProfile(
                name=code, code=code,
                avg_home_goals=d.get('avg_home_goals', 1.50),
                avg_away_goals=d.get('avg_away_goals', 1.15),
                avg_total_goals=d.get('avg_total_goals', 2.65),
                home_win_rate=d.get('home_win_rate', 0.45),
                draw_rate=d.get('draw_rate', 0.25),
                away_win_rate=d.get('away_win_rate', 0.30),
                home_advantage_elo=round((d.get('home_goal_boost') or 0.30) * 300),
                home_goal_boost=d.get('home_goal_boost', 0.30),
                over_25_rate=d.get('over_25_rate', 0.50),
                btts_rate=d.get('btts_rate', 0.52),
                avg_corners=d.get('avg_corners') or 9.8,
                corner_home_share=d.get('corner_home_share') or 0.55,
                style=d.get('style', ''),
                multi_season=d.get('multi_season') or [],
            )
        except Exception:
            continue
    return out


# 实测优先, 手写兜底 —— 缺失的联赛(如新加的)才用 _HARDCODED / 通用默认
LEAGUE_PROFILES: dict[str, LeagueProfile] = dict(_HARDCODED)
LEAGUE_PROFILES.update(_load_data_profiles())


def get_profile(league_code: str) -> LeagueProfile:
    """Get league profile, falling back to generic default."""
    code = league_code.upper()
    if code in LEAGUE_PROFILES:
        return LEAGUE_PROFILES[code]
    # Generic default
    return LeagueProfile(name=league_code, code=code)


def compute_league_profiles_from_matches(matches: list[dict]) -> dict[str, LeagueProfile]:
    """Compute league profiles directly from historical match data.

    This overrides hardcoded values with actual measured statistics.
    """
    from collections import defaultdict

    stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "home_wins": 0, "draws": 0, "away_wins": 0,
        "total_goals": 0, "home_goals": 0, "away_goals": 0,
        "over_25": 0, "btts": 0,
    })

    for m in matches:
        s = stats[m["league_code"]]
        s["total"] += 1
        s["total_goals"] += m["home_goals"] + m["away_goals"]
        s["home_goals"] += m["home_goals"]
        s["away_goals"] += m["away_goals"]

        if m["result"] == "H":
            s["home_wins"] += 1
        elif m["result"] == "D":
            s["draws"] += 1
        else:
            s["away_wins"] += 1

        if m["home_goals"] + m["away_goals"] > 2.5:
            s["over_25"] += 1
        if m["home_goals"] > 0 and m["away_goals"] > 0:
            s["btts"] += 1

    profiles = {}
    for code, s in stats.items():
        n = s["total"]
        if n < 10:
            continue

        home_adv = (s["home_goals"] / s["away_goals"] - 1) if s["away_goals"] > 0 else 0.30

        profiles[code] = LeagueProfile(
            name=code, code=code,
            avg_home_goals=round(s["home_goals"] / n, 2),
            avg_away_goals=round(s["away_goals"] / n, 2),
            avg_total_goals=round(s["total_goals"] / n, 2),
            home_win_rate=round(s["home_wins"] / n, 4),
            draw_rate=round(s["draws"] / n, 4),
            away_win_rate=round(s["away_wins"] / n, 4),
            home_advantage_elo=round(home_adv * 300),
            home_goal_boost=round(home_adv, 4),
            over_25_rate=round(s["over_25"] / n, 4),
            btts_rate=round(s["btts"] / n, 4),
        )

    return profiles
