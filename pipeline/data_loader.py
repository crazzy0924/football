"""
Historical CSV Data Loader

Parses football-data.co.uk CSV files into a unified match record format.
Handles:
- BOM character in first CSV line
- Date parsing (DD/MM/YYYY)
- Team name normalization across seasons
- Extracts match results + closing odds from multiple bookmakers
"""
from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


# League code mapping: football-data.co.uk Div codes → internal codes
DIV_TO_LEAGUE = {
    "E0": "PL",   # Premier League
    "SP1": "PD",  # La Liga
    "D1": "BL1",  # Bundesliga
    "I1": "SA",   # Serie A
    "F1": "FL1",  # Ligue 1
}

# Odds columns we extract (bookmaker prefix → output key)
ODDS_COLUMNS = {
    "B365": "bet365",
    "PS": "pinnacle",
    "BW": "betwin",
    "BF": "betfair",
    "WH": "william_hill",
    "VC": "vc_bet",
    "IW": "interwetten",
}

# CSV seasons to expected season label
SEASON_PATTERN = re.compile(r"(\d{4})_(\d{4})\.csv$")


def parse_season_from_filename(filename: str) -> str:
    """Extract season label from filename like 'E0_2021_2022.csv' → '21-22'"""
    m = SEASON_PATTERN.search(filename)
    if m:
        return f"{m.group(1)[2:]}-{m.group(2)[2:]}"
    return "unknown"


def load_all_csvs(csv_dir: str = "data/historical_odds") -> list[dict]:
    """Load all CSV files from the historical odds directory.

    Returns:
        list of match dicts sorted chronologically. Each dict:
        {
            "league_code": "PL",
            "season": "21-22",
            "date": "2021-08-13",
            "home_team": "Brentford",
            "away_team": "Arsenal",
            "home_goals": 2,
            "away_goals": 0,
            "result": "H",  # H/D/A
            "odds": {
                "bet365": {"home": 3.1, "draw": 3.4, "away": 2.25},
                "pinnacle": {"home": 3.13, "draw": 3.38, "away": 2.26},
                ...
            }
        }
    """
    all_matches = []
    csv_files = sorted(Path(csv_dir).glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {csv_dir}")

    for csv_path in csv_files:
        filename = csv_path.name
        div_code = filename.split("_")[0]
        league_code = DIV_TO_LEAGUE.get(div_code, div_code)
        season = parse_season_from_filename(filename)

        matches = _parse_csv(csv_path, league_code, season)
        all_matches.extend(matches)

    # Sort chronologically
    all_matches.sort(key=lambda m: m["date"])
    return all_matches


def _parse_csv(csv_path: Path, league_code: str, season: str) -> list[dict]:
    """Parse a single CSV file."""
    matches = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                match = _parse_row(row, league_code, season)
                if match:
                    matches.append(match)
            except (ValueError, KeyError):
                continue

    return matches


def _parse_row(row: dict, league_code: str, season: str) -> dict | None:
    """Parse a single CSV row into a match record."""
    # Required fields
    home_goals_str = row.get("FTHG", "")
    away_goals_str = row.get("FTAG", "")
    if not home_goals_str or not away_goals_str:
        return None

    home_goals = int(home_goals_str)
    away_goals = int(away_goals_str)
    result = row.get("FTR", "")

    # Date parsing
    date_str = row.get("Date", "")
    date_iso = _parse_date(date_str)

    # Team names
    home_team = row.get("HomeTeam", "").strip()
    away_team = row.get("AwayTeam", "").strip()
    if not home_team or not away_team:
        return None

    # Extract odds
    odds = {}
    for prefix, label in ODDS_COLUMNS.items():
        h_col = f"{prefix}H"
        d_col = f"{prefix}D"
        a_col = f"{prefix}A"
        if h_col in row and d_col in row and a_col in row:
            try:
                h = float(row[h_col])
                d = float(row[d_col])
                a = float(row[a_col])
                if h > 1.0 and d > 1.0 and a > 1.0:
                    odds[label] = {"home": h, "draw": d, "away": a}
            except (ValueError, TypeError):
                pass

    return {
        "league_code": league_code,
        "season": season,
        "date": date_iso,
        "home_team": normalize_team_name(home_team),
        "away_team": normalize_team_name(away_team),
        "home_goals": home_goals,
        "away_goals": away_goals,
        "result": result,
        "odds": odds,
    }


def _parse_date(date_str: str) -> str:
    """Parse DD/MM/YYYY or DD/MM/YY → ISO YYYY-MM-DD."""
    date_str = date_str.strip()
    parts = date_str.split("/")
    if len(parts) != 3:
        return date_str

    day, month, year = parts
    if len(year) == 2:
        year = "20" + year

    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


# Canonical team name aliases — maps API names to CSV names
TEAM_NAME_ALIASES = {
    # Bundesliga
    "Borussia Dortmund": "Dortmund",
    "Borussia M'gladbach": "M'gladbach",
    "Borussia Mönchengladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Cologne": "FC Koln",
    "1. FC Koln": "FC Koln",
    "RB Leipzig": "RB Leipzig",
    "Bayer Leverkusen": "Leverkusen",
    "Greuther Fürth": "Greuther Furth",
    "St. Pauli": "St Pauli",
    "Holstein Kiel": "Holstein Kiel",
    # Serie A
    "AC Milan": "Milan",
    "Inter Milan": "Inter",
    "Internazionale": "Inter",
    "Atalanta BC": "Atalanta",
    "Atalanta Bergamo": "Atalanta",
    "Nottingham Forest": "Nott'm Forest",
    "Nottm Forest": "Nott'm Forest",
    # La Liga
    "Atletico Madrid": "Ath Madrid",
    "Atlético Madrid": "Ath Madrid",
    "Athletic Bilbao": "Ath Bilbao",
    "Athletic Club": "Ath Bilbao",
    "Real Sociedad": "Sociedad",
    "Rayo Vallecano": "Vallecano",
    "Real Valladolid": "Valladolid",
    "Espanyol": "Espanol",
    "Almería": "Almeria",
    "Cádiz": "Cadiz",
    "Girona FC": "Girona",
    "Granada CF": "Granada",
    "Málaga": "Malaga",
    # Premier League
    "Manchester City": "Man City",
    "Manchester Utd": "Man United",
    "Manchester United": "Man United",
    "Wolverhampton": "Wolves",
    "Wolverhampton Wanderers": "Wolves",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham",
    "Leicester City": "Leicester",
    "Leeds United": "Leeds",
    "Newcastle Utd": "Newcastle",
    "Newcastle United": "Newcastle",
    "Sheffield Utd": "Sheffield United",
    "Crystal Palace": "Crystal Palace",
    "Brighton & Hove Albion": "Brighton",
    # Ligue 1
    "Paris Saint-Germain": "Paris SG",
    "Paris Saint Germain": "Paris SG",
    "Saint-Etienne": "St Etienne",
    "AS Saint-Etienne": "St Etienne",
    "Saint-Étienne": "St Etienne",
    "Olympique Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "OGC Nice": "Nice",
    "RC Strasbourg": "Strasbourg",
    "Strasbourg Alsace": "Strasbourg",
    "LOSC Lille": "Lille",
    "FC Nantes": "Nantes",
    "Stade Brestois": "Brest",
    "Stade Brest": "Brest",
    "Stade Rennais": "Rennes",
    "Stade de Reims": "Reims",
    "Montpellier HSC": "Montpellier",
    "Clermont Foot": "Clermont",
    "FC Lorient": "Lorient",
    "AC Ajaccio": "Ajaccio",
    "Troyes AC": "Troyes",
    "AJ Auxerre": "Auxerre",
    "Le Havre AC": "Le Havre",
    "FC Metz": "Metz",
    "RC Lens": "Lens",
    "AS Monaco": "Monaco",
    "Toulouse FC": "Toulouse",
    "Angers SCO": "Angers",
}


def normalize_team_name(name: str) -> str:
    """Normalize team name to canonical CSV form.

    Maps common API/spelling variants to the names used in football-data.co.uk CSVs.
    """
    name = name.strip()
    name = name.replace("&", "&")
    name = name.replace("´", "'")

    # Check alias map
    if name in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[name]

    return name


def detect_team_name_variants(matches: list[dict]) -> dict[str, list[str]]:
    """Detect potential team name variants across seasons.

    Returns dict of canonical_name → [variant1, variant2, ...]
    for manual review and correction.
    """
    # Group teams by league
    league_teams: dict[str, set[str]] = defaultdict(set)
    for m in matches:
        league_teams[m["league_code"]].add(m["home_team"])
        league_teams[m["league_code"]].add(m["away_team"])

    # For each league, find fuzzy matches
    variants: dict[str, list[str]] = {}
    for league, teams in league_teams.items():
        team_list = sorted(teams)
        for i, t1 in enumerate(team_list):
            for t2 in team_list[i + 1 :]:
                if _is_likely_same_team(t1, t2):
                    if t1 not in variants:
                        variants[t1] = []
                    variants[t1].append(t2)

    return variants


def _is_likely_same_team(a: str, b: str) -> bool:
    """Heuristic: are these likely the same team with different spellings?"""
    # Normalize for comparison
    a_norm = a.lower().replace(" ", "").replace(".", "").replace("'", "")
    b_norm = b.lower().replace(" ", "").replace(".", "").replace("'", "")

    # Exact match after normalization
    if a_norm == b_norm:
        return a != b  # Only if original strings differ

    # One contains the other
    if a_norm in b_norm or b_norm in a_norm:
        return True

    # Levenshtein-like: share long common prefix
    common = 0
    for c1, c2 in zip(a_norm, b_norm):
        if c1 == c2:
            common += 1
        else:
            break
    if len(a_norm) > 5 and len(b_norm) > 5 and common >= min(len(a_norm), len(b_norm)) - 3:
        return True

    return False


def matches_by_league(matches: list[dict]) -> dict[str, list[dict]]:
    """Group matches by league code."""
    groups = defaultdict(list)
    for m in matches:
        groups[m["league_code"]].append(m)
    return dict(groups)


def matches_by_season(matches: list[dict]) -> dict[str, list[dict]]:
    """Group matches by season."""
    groups = defaultdict(list)
    for m in matches:
        groups[m["season"]].append(m)
    return dict(groups)


def compute_league_stats(matches: list[dict]) -> dict[str, dict]:
    """Compute actual league statistics from match data.

    Returns dict of league_code → {home_win_rate, draw_rate, avg_goals, ...}
    """
    stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "home_wins": 0, "draws": 0, "away_wins": 0,
        "total_goals": 0, "over_25": 0, "btts": 0,
    })

    for m in matches:
        s = stats[m["league_code"]]
        s["total"] += 1
        s["total_goals"] += m["home_goals"] + m["away_goals"]

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

    result = {}
    for code, s in stats.items():
        n = s["total"]
        if n == 0:
            continue
        result[code] = {
            "home_win_rate": round(s["home_wins"] / n, 4),
            "draw_rate": round(s["draws"] / n, 4),
            "away_win_rate": round(s["away_wins"] / n, 4),
            "avg_total_goals": round(s["total_goals"] / n, 2),
            "over_25_rate": round(s["over_25"] / n, 4),
            "btts_rate": round(s["btts"] / n, 4),
        }
    return result
