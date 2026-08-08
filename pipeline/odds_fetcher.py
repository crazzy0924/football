"""
Odds Fetcher v3.0

Fetches today's football matches with odds from odds-api.io.
Simplified from the v2.0 fetch_kambi.py approach.
Falls back gracefully to stub data when API is unavailable.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import config


def fetch_today_matches(sport: str = "soccer_europe") -> list[dict]:
    """Fetch today's football matches with odds.

    Uses odds-api.io (Kambi/Unibet odds).
    Falls back to stub if API key is not configured.

    Returns:
        list of dicts with: home_team, away_team, league_code, odds
    """
    api_key = config.ODDS_API_KEY

    if not api_key:
        print("ODDS_API_IO_KEY not configured. Using stub data.")
        return _stub_matches()

    try:
        import httpx

        today = date.today().isoformat()
        url = f"https://api.odds-api.io/v4/sports/{sport}/odds"
        params = {
            "apiKey": api_key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        with httpx.Client(timeout=15) as client:
            # First get events
            events_url = f"https://api.odds-api.io/v4/sports/{sport}/events"
            events_resp = client.get(events_url, params={"apiKey": api_key, "dateFormat": "iso"})
            if events_resp.status_code != 200:
                print(f"Events API error: {events_resp.status_code}")
                return _stub_matches()

            events = events_resp.json()
            if not events:
                print("No events found for today.")
                return []

            # Get odds for these events
            event_ids = [e["id"] for e in events[:50]]  # cap at 50
            odds_resp = client.get(
                url,
                params={**params, "eventIds": ",".join(event_ids)},
            )
            if odds_resp.status_code != 200:
                print(f"Odds API error: {odds_resp.status_code}")
                return _stub_matches()

            odds_data = odds_resp.json()

        return _parse_odds_response(events, odds_data)

    except Exception as e:
        print(f"Error fetching odds: {e}")
        return _stub_matches()


def _parse_odds_response(events: list, odds_data: list) -> list[dict]:
    """Parse odds-api.io response into our match format."""
    matches = []

    # Build event lookup
    event_map = {}
    for e in events:
        event_map[e["id"]] = e

    for odds_entry in odds_data:
        eid = odds_entry.get("id") or odds_entry.get("event_id")
        event = event_map.get(eid, {})
        home = event.get("home_team", odds_entry.get("home_team", ""))
        away = event.get("away_team", odds_entry.get("away_team", ""))
        league = event.get("sport_title", event.get("league", ""))

        if not home or not away:
            continue

        # Find Unibet/Kambi odds
        bookmakers = odds_entry.get("bookmakers", [])
        unibet_odds = None
        for bm in bookmakers:
            if "unibet" in bm.get("key", "").lower():
                markets = bm.get("markets", [])
                for mk in markets:
                    if mk.get("key") == "h2h":
                        outcomes = mk.get("outcomes", [])
                        if len(outcomes) >= 3:
                            unibet_odds = {
                                "home": outcomes[0]["price"],
                                "draw": outcomes[1]["price"],
                                "away": outcomes[2]["price"],
                            }
                        break
                break

        if not unibet_odds:
            continue

        # Map league to our code
        league_code = _map_league(league)

        matches.append({
            "home_team": home,
            "away_team": away,
            "league_code": league_code,
            "league_name": league,
            "odds": unibet_odds,
        })

    return matches


def _map_league(sport_title: str) -> str:
    """Map odds-api league name to our internal league code."""
    title = sport_title.lower()
    mapping = {
        "premier league": "PL",
        "la liga": "PD",
        "bundesliga": "BL1",
        "serie a": "SA",
        "ligue 1": "FL1",
        "eredivisie": "DED",
        "primeira liga": "PPL",
        "championship": "ELC",
        "mls": "MLS",
        "brazil serie a": "BSA",
        "j1 league": "J1",
        "j league": "J1",
        "k league": "KLEAGUE",
        "belgian pro league": "BEL",
        "swiss super league": "SWI",
        "austrian bundesliga": "AUT",
        "danish superliga": "DEN",
        "norwegian eliteserien": "NOR",
        "swedish allsvenskan": "SWE",
        "polish ekstraklasa": "POL",
        "czech liga 1": "CZE",
    }
    for query, code in mapping.items():
        if query in title:
            return code
    return title[:3].upper()


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
