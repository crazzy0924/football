"""
Odds Fetcher v3.0 (Fixed)

Fetches today's football matches with odds from the-odds-api.com v4.
Previously used wrong base URL (odds-api.io) and wrong API version (v4 on a v3 API).
Now correctly uses api.the-odds-api.com/v4.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone, timedelta
from typing import Any

import config

# All available soccer sport keys from the-odds-api.com v4 (42 total)
DEFAULT_SPORT_KEYS = [
    # Tier 1: Big 5 + major European
    "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
    "soccer_italy_serie_a", "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie", "soccer_portugal_primeira_liga",
    "soccer_efl_champ",
    # Tier 2: Other Europe
    "soccer_belgium_first_div", "soccer_austria_bundesliga",
    "soccer_denmark_superliga", "soccer_norway_eliteserien",
    "soccer_sweden_allsvenskan", "soccer_poland_ekstraklasa",
    "soccer_finland_veikkausliiga", "soccer_germany_bundesliga2",
    "soccer_france_ligue_two", "soccer_italy_serie_b",
    "soccer_spain_segunda_division", "soccer_greece_super_league",
    "soccer_turkey_super_league", "soccer_russia_premier_league",
    # Tier 3: Americas + Asia
    "soccer_brazil_campeonato", "soccer_brazil_serie_b",
    "soccer_japan_j_league", "soccer_korea_kleague1",
    "soccer_usa_mls", "soccer_mexico_ligamx",
    "soccer_argentina_primera_division",
    "soccer_china_superleague",
    # Tier 4: England lower + cups
    "soccer_england_league1", "soccer_england_league2",
    "soccer_england_efl_cup", "soccer_germany_dfb_pokal",
    "soccer_germany_liga3",
    # Continental
    "soccer_uefa_champs_league_qualification",
    "soccer_uefa_nations_league",
    "soccer_conmebol_copa_libertadores",
    "soccer_conmebol_copa_sudamericana",
    "soccer_concacaf_leagues_cup",
    "soccer_chile_campeonato",
]

# the-odds-api sport_title → internal league code mapping
LEAGUE_MAP = {
    "epl": "PL",
    "la liga": "PD",
    "bundesliga": "BL1",
    "serie a": "SA",
    "ligue 1": "FL1",
    "ligue 2": "FL2",
    "serie b": "SB",
    "eredivisie": "DED",
    "primeira liga": "PPL",
    "championship": "ELC",
    "league 1": "EL1",
    "league 2": "EL2",
    "efl cup": "EFL",
    "mls": "MLS",
    "brazil série a": "BSA",
    "brazil série b": "BSB",
    "j league": "J1",
    "k league 1": "KLEAGUE",
    "belgium first div": "BEL",
    "austrian football bundesliga": "AUT",
    "denmark superliga": "DEN",
    "eliteserien": "NOR",
    "allsvenskan": "SWE",
    "ekstraklasa": "POL",
    "super league": "GSL",  # Greece
    "turkey super league": "TUR",
    "bundesliga 2": "BL2",
    "veikkausliiga": "FIN",
    "la liga 2": "PD2",
    "liga mx": "LMX",
    "primera división": "ARG",  # Argentina
    "super league - china": "CSL",
    "dfb-pokal": "DFB",
    "3. liga": "BL3",
    "copa libertadores": "LIB",
    "copa sudamericana": "SUD",
    "champions league qualification": "UCLQ",
    "nations league": "UNL",
    "leagues cup": "LCUP",
    "superettan": "SWE2",
    "russia premier league": "RPL",
    "chile": "CHI",
}


def fetch_today_matches(
    sport_keys: list[str] | None = None,
    bookmakers: str = "unibet",
    date_str: str | None = None,
) -> list[dict]:
    """Fetch today's football matches with odds from the-odds-api.com v4.

    Args:
        sport_keys: list of sport keys (default: DEFAULT_SPORT_KEYS)
        bookmakers: comma-separated bookmaker keys (default: "unibet")
        date_str: target date in YYYY-MM-DD (default: today Beijing time)

    Returns:
        list of dicts with: home_team, away_team, league_code, odds, kickoff
    """
    api_key = config.THE_ODDS_API_KEY or config.ODDS_API_IO_KEY

    if not api_key:
        print("No odds API key configured. Use stub data.")
        return _stub_matches()

    if sport_keys is None:
        sport_keys = DEFAULT_SPORT_KEYS

    # Default: today Beijing time
    beijing_tz = timezone(timedelta(hours=8))
    if date_str is None:
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")

    all_matches = []

    try:
        import httpx

        with httpx.Client(timeout=20) as client:
            for sport_key in sport_keys:
                url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
                params = {
                    "apiKey": api_key,
                    "regions": "eu",
                    "markets": "h2h",
                    "bookmakers": bookmakers,
                    "oddsFormat": "decimal",
                    "dateFormat": "iso",
                }

                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    print(f"  {sport_key}: HTTP {resp.status_code} — {resp.text[:120]}")
                    continue

                events = resp.json()
                if not events:
                    continue

                # Filter by target date (Beijing time)
                for e in events:
                    ct = e.get("commence_time", "")
                    if not ct:
                        continue
                    try:
                        utc_time = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                        bj_time = utc_time.astimezone(beijing_tz)
                        if bj_time.strftime("%Y-%m-%d") != date_str:
                            continue
                    except (ValueError, TypeError):
                        continue

                    home = e.get("home_team", "")
                    away = e.get("away_team", "")
                    sport_title = e.get("sport_title", "")

                    if not home or not away:
                        continue

                    # Extract H2H odds from first bookmaker
                    h2h_odds = None
                    for bm in e.get("bookmakers", []):
                        for mkt in bm.get("markets", []):
                            if mkt.get("key") == "h2h":
                                outcomes = mkt.get("outcomes", [])
                                if len(outcomes) >= 3:
                                    # outcomes order: home, draw, away
                                    h2h_odds = {
                                        "home": outcomes[0]["price"],
                                        "draw": outcomes[1]["price"],
                                        "away": outcomes[2]["price"],
                                    }
                                break
                        if h2h_odds:
                            break

                    if not h2h_odds:
                        continue

                    league_code = _map_league(sport_title)

                    all_matches.append({
                        "home_team": home,
                        "away_team": away,
                        "league_code": league_code,
                        "league_name": sport_title,
                        "odds": h2h_odds,
                        "kickoff": ct,
                        "source": "the-odds-api.com",
                    })

        return all_matches

    except Exception as e:
        print(f"Error fetching odds: {e}")
        return _stub_matches()


def _map_league(sport_title: str) -> str:
    """Map the-odds-api sport_title to internal league code."""
    title_lower = sport_title.lower().strip()
    # Exact match first
    if title_lower in LEAGUE_MAP:
        return LEAGUE_MAP[title_lower]
    # Substring match (longer patterns first)
    for pattern, code in sorted(LEAGUE_MAP.items(), key=lambda x: -len(x[0])):
        if pattern in title_lower:
            return code
    # Fallback
    return title_lower[:3].upper()


def _stub_matches() -> list[dict]:
    """Stub match data for testing when API is unavailable."""
    today = date.today().isoformat()
    return [
        {
            "home_team": "Liverpool",
            "away_team": "Arsenal",
            "league_code": "PL",
            "odds": {"home": 2.10, "draw": 3.50, "away": 3.80},
        },
        {
            "home_team": "Barcelona",
            "away_team": "Real Madrid",
            "league_code": "PD",
            "odds": {"home": 2.40, "draw": 3.30, "away": 3.10},
        },
    ]
