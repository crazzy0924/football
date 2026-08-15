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

# the-odds-api.com v4 全部足球赛事键 (共42个)
DEFAULT_SPORT_KEYS = [
    # 一级: 五大联赛 + 欧洲主流
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
    # 三级: 美洲 + 亚洲
    "soccer_brazil_campeonato", "soccer_brazil_serie_b",
    "soccer_japan_j_league", "soccer_korea_kleague1",
    "soccer_usa_mls", "soccer_mexico_ligamx",
    "soccer_argentina_primera_division",
    "soccer_china_superleague",
    # 四级: 英格兰低级别 + 杯赛
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

# the-odds-api sport_title → 内部联赛代码映射
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
        print("未配置赔率API密钥，使用桩数据。")
        return _stub_matches()

    if sport_keys is None:
        sport_keys = DEFAULT_SPORT_KEYS

    # 默认: 今日北京时间
    beijing_tz = timezone(timedelta(hours=8))
    if date_str is None:
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")

    all_matches = []

    try:
        import httpx

        quota_exhausted = False
        with httpx.Client(timeout=20) as client:
            for sport_key in sport_keys:
                if quota_exhausted:
                    break  # skip remaining calls once quota confirmed dead
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
                # Phase 1 A1: 配额余量提前告警 (the-odds-api 在 header 返回余量)
                if resp.headers.get("x-requests-remaining") == "0":
                    quota_exhausted = True
                    print("  the-odds-api 配额已用尽 (x-requests-remaining: 0)")
                if resp.status_code != 200:
                    if resp.status_code in (401, 403):
                        print(f"  赔率API配额耗尽 ({resp.status_code})，跳过其余联赛")
                        quota_exhausted = True
                    continue

                events = resp.json()
                if not events:
                    continue

                # 按目标日期过滤 (北京时间)
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

                    # 从第一家博彩商提取胜平负赔率
                    h2h_odds = None
                    for bm in e.get("bookmakers", []):
                        for mkt in bm.get("markets", []):
                            if mkt.get("key") == "h2h":
                                outcomes = mkt.get("outcomes", [])
                                if len(outcomes) >= 3:
                                    # 结果顺序: 主胜, 平局, 客胜
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

        # Phase 1 A1: the-odds-api 无结果或配额耗尽 → odds-api.io v3 兜底
        if not all_matches or quota_exhausted:
            print("  the-odds-api 无可用结果，切换到 odds-api.io v3 兜底...")
            fallback = fetch_oddsapi_io_matches(date_str=date_str)
            if fallback:
                all_matches = fallback

        return all_matches

    except Exception as e:
        print(f"拉取赔率出错: {e}")
        return _stub_matches()


# ═══════════════════════════════════════════════════════════
# Phase 1 A1: odds-api.io v3 兜底源 (2026-08-14 加入)
# the-odds-api 配额耗尽时自动切换; 需 ODDS_API_IO_KEY
# ═══════════════════════════════════════════════════════════
ODDSAPI_IO_LEAGUE_SLUG_MAP = {
    'england-premier-league': 'PL', 'spain-la-liga': 'PD',
    'germany-bundesliga': 'BL1', 'italy-serie-a': 'SA',
    'france-ligue-1': 'FL1', 'england-championship': 'ELC',
    'germany-bundesliga-2': 'BL2', 'spain-la-liga-2': 'PD2',
    'france-ligue-2': 'FL2', 'italy-serie-b': 'SB',
    'netherlands-eredivisie': 'DED', 'portugal-liga-portugal': 'PPL',
    'belgium-first-division-a': 'BPL', 'turkiye-super-lig': 'TUR',
    'greece-super-league': 'GRE', 'norway-eliteserien': 'NO1',
    'sweden-allsvenskan': 'SWE', 'finland-veikkausliiga': 'FIN',
    'scotland-premiership': 'SPL', 'brazil-brasileiro-a': 'BSA',
    'brazil-brasileiro-b': 'BS1', 'argentina-primera-division': 'ARG',
    'usa-mls': 'MLS', 'japan-j1-league': 'J1', 'japan-j2-league': 'J2',
    'international-clubs-uefa-champions-league-qualification': 'UCL',
    'international-clubs-uefa-europa-league-qualification': 'UEL',
    'international-clubs-uefa-conference-league-qualification': 'UEC',
    'international-clubs-conmebol-libertadores-knockout-stage': 'CLB',
    'international-clubs-conmebol-sudamericana-knockout-stage': 'CSD',
    'international-clubs-leagues-cup-group-stage': 'LGC',
    'england-league-1': 'EL1', 'england-league-2': 'EL2',
    'england-efl-cup': 'EFL', 'germany-3-liga': 'BL3',
    'russia-premier-league': 'RPL', 'korea-k-league-1': 'KLEAGUE',
    'china-super-league': 'CSL', 'mexico-liga-mx': 'LMX',
    'austria-bundesliga': 'AUT', 'denmark-superligaen': 'DEN',
    'poland-ekstraklasa': 'POL', 'serbia-super-liga': 'SRB',
    'slovenia-prvaliga': 'SVN', 'croatia-hnl': 'HRV',
    'slovakia-superliga': 'SVK', 'hungary-nb-i': 'HUN',
    'colombia-torneo-dimayor-clausura': 'COL',
    'chile-liga-de-ascenso': 'CHI',
}


def fetch_oddsapi_io_matches(
    date_str: str | None = None,
    max_matches: int = 60,
    bookmaker: str = "Kambi",
) -> list[dict]:
    """odds-api.io v3 fallback: events + Kambi ML odds.

    the-odds-api.com 配额耗尽时的兜底源 (Phase 1 A1).
    返回与 fetch_today_matches 相同 schema。
    """
    key = config.ODDS_API_IO_KEY
    if not key:
        print("  odds-api.io: 未配置 ODDS_API_IO_KEY，无法兜底")
        return []

    import httpx

    beijing_tz = timezone(timedelta(hours=8))
    if date_str is None:
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")

    all_matches: list[dict] = []
    try:
        with httpx.Client(timeout=15, verify=False) as client:
            resp = client.get(
                f"https://api.odds-api.io/v3/events?apiKey={key}&sport=football&limit=1000"
            )
            if resp.status_code != 200:
                print(f"  odds-api.io 赛事接口: HTTP {resp.status_code}")
                return []
            events = resp.json()

            day_events = []
            for e in events:
                ct = e.get("date", "")
                if not ct:
                    continue
                try:
                    utc_time = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    bj = utc_time.astimezone(beijing_tz)
                except (ValueError, TypeError):
                    continue
                if bj.strftime("%Y-%m-%d") != date_str:
                    continue
                slug = (e.get("league") or {}).get("slug", "")
                lc = ODDSAPI_IO_LEAGUE_SLUG_MAP.get(slug)
                if not lc:
                    continue
                day_events.append({
                    "id": e["id"],
                    "home": e.get("home", ""),
                    "away": e.get("away", ""),
                    "league_code": lc,
                    "kickoff": bj.isoformat(),
                })
            print(f"  odds-api.io: {date_str} 可映射 {len(day_events)} 场")

            for i, ev in enumerate(day_events[:max_matches]):
                if not ev["home"] or not ev["away"]:
                    continue
                url = f"https://api.odds-api.io/v3/odds?apiKey={key}&eventId={ev['id']}&bookmakers={bookmaker}"
                try:
                    r = client.get(url)
                except Exception as ex:
                    print(f"    [{i+1}] {ev['home']} vs {ev['away']}: 请求失败 {ex}")
                    continue
                if r.status_code != 200:
                    continue
                data = r.json()
                bms = data.get("bookmakers", {})
                markets = bms.get(bookmaker, []) if isinstance(bms, dict) else []
                h2h = None
                for mkt in markets:
                    if mkt.get("name") == "ML" and mkt.get("odds"):
                        o = mkt["odds"][0]
                        h2h = {
                            "home": float(o["home"]),
                            "draw": float(o["draw"]),
                            "away": float(o["away"]),
                        }
                        break
                if h2h:
                    all_matches.append({
                        "home_team": ev["home"],
                        "away_team": ev["away"],
                        "league_code": ev["league_code"],
                        "odds": h2h,
                        "kickoff": ev["kickoff"],
                        "source": "odds-api.io",
                    })
        print(f"  odds-api.io: 拿到 {len(all_matches)} 场带赔率")
        return all_matches
    except Exception as e:
        print(f"  odds-api.io 拉取失败: {e}")
        return []


def _map_league(sport_title: str) -> str:
    """Map the-odds-api sport_title to internal league code."""
    title_lower = sport_title.lower().strip()
    # Exact match first
    if title_lower in LEAGUE_MAP:
        return LEAGUE_MAP[title_lower]
    # 子串匹配 (长模式优先)
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
