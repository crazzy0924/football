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


# 联赛代码映射: football-data.co.uk Div代码 → 内部代码
DIV_TO_LEAGUE = {
    "E0": "PL",   # Premier League
    "E1": "ELC",  # Championship
    "SP1": "PD",  # La Liga
    "SP2": "PD2",  # La Liga 2
    "D1": "BL1",  # Bundesliga
    "D2": "BL2",  # 2. Bundesliga
    "I1": "SA",   # Serie A
    "I2": "SB",   # Serie B
    "F1": "FL1",  # Ligue 1
    "F2": "FL2",  # Ligue 2
    "N1": "DED",  # Eredivisie
    "P1": "PPL",  # Primeira Liga
    "SC0": "SPL",  # Scotland Premiership
    "B1": "BPL",  # Belgium Pro League
    "T1": "TUR",  # Turkey Super Lig
    "G1": "GRE",  # Greece Super League
}

# 抽取的赔率列 (博彩商前缀 → 输出键)
ODDS_COLUMNS = {
    "B365": "bet365",
    "PS": "pinnacle",
    "BW": "betwin",
    "BF": "betfair",
    "WH": "william_hill",
    "VC": "vc_bet",
    "IW": "interwetten",
}

# CSV赛季 → 期望赛季标签
# 兼容 "E0_2021_2022.csv" 与 "D2_2425.csv" 两种文件名格式
SEASON_PATTERN = re.compile(r"_(\d{4})_(\d{4})\.csv$")
SEASON_PATTERN_SHORT = re.compile(r"_(\d{2})(\d{2})\.csv$")


def parse_season_from_filename(filename: str) -> str:
    """Extract season label from filename like 'E0_2021_2022.csv' or 'D2_2425.csv' → '21-22'"""
    m = SEASON_PATTERN.search(filename)
    if m:
        return f"{m.group(1)[2:]}-{m.group(2)[2:]}"
    m = SEASON_PATTERN_SHORT.search(filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
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

    # 按时间排序
    all_matches.sort(key=lambda m: m["date"])
    return all_matches


def load_openfootball_matches(json_path: str = "data/openfootball_matches.json") -> list[dict]:
    """Load parsed openfootball match data (J1, SWE, NOR, FIN, BSA).

    These leagues are not covered by football-data.co.uk CSVs.
    Data parsed from openfootball/{world,europe,south-america} repos.
    No odds available — only match results for ELO + Dixon-Coles training.

    Returns:
        list of match dicts with same schema as load_all_csvs (minus odds)
    """
    import json as _json
    from pathlib import Path as _Path

    json_path = _Path(json_path)
    if not json_path.exists():
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        raw = _json.load(f)

    matches = []
    for m in raw:
        hg = m.get("home_goals", 0)
        ag = m.get("away_goals", 0)
        if hg > ag:
            result = "H"
        elif ag > hg:
            result = "A"
        else:
            result = "D"

        matches.append({
            "league_code": m["league_code"],
            "season": m.get("season", "unknown"),
            "date": m["date"],
            "home_team": normalize_team_name(m["home_team"]),
            "away_team": normalize_team_name(m["away_team"]),
            "home_goals": hg,
            "away_goals": ag,
            "result": result,
            "odds": {},  # no odds data in openfootball
        })

    return matches


def load_local_db_matches(json_path: str = "data/local_match_db.json") -> list[dict]:
    """加载 h2h 全库中训练集未覆盖的场次 (Phase 1 A3).

    local_match_db.json 由 h2h.py --rebuild 构建, 含 4 个来源:
      - football_data_csv  (已在 CSV 训练集中)
      - openfootball_json (已在 openfootball_matches.json 中)
      - openfootball_txt  (巴西杯/挪威杯/瑞典低级别等, 训练集未覆盖 → 本次并入)
      - 首轮回补/复盘回灌 (实盘赛果回灌)
    """
    import json as _json
    from pathlib import Path as _Path

    json_path = _Path(json_path)
    if not json_path.exists():
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        db = _json.load(f)

    matches = []
    for m in db.get("matches", []):
        src = m.get("source", "")
        if src in ("football_data_csv", "openfootball_json"):
            continue
        hg = m.get("home_goals")
        ag = m.get("away_goals")
        if hg is None or ag is None:
            continue
        # 联赛代码缺失/未知的杂项不入训练
        lg = m.get("league_code") or ""
        if not lg or lg == "UNK":
            continue
        # 赛季归一: 年份制(如2023) → 欧赛季制(22-23), 与CSV标签对齐
        season = str(m.get("season") or "")
        if len(season) == 4 and season.isdigit():
            y = int(season)
            season = f"{y - 1:04d}"[2:] + "-" + f"{y:04d}"[2:]
        if not season or season == "unknown":
            continue
        date = m.get("date") or ""
        if not date:
            continue
        matches.append({
            "league_code": lg,
            "season": season,
            "date": date,
            "home_team": normalize_team_name(m.get("home_team", "")),
            "away_team": normalize_team_name(m.get("away_team", "")),
            "home_goals": int(hg),
            "away_goals": int(ag),
            "result": m.get("result", ""),
            "odds": {},
        })
    return matches


def load_all_matches(csv_dir: str = "data/historical_odds",
                     openfootball_json: str = "data/openfootball_matches.json",
                     local_db_json: str = "data/local_match_db.json") -> list[dict]:
    """Load ALL match data: CSV + openfootball JSON + h2h全库增量 (Phase 1 A3).

    按 (date, league_code, home_team, away_team) 去重后按时间排序。
    """
    matches = load_all_csvs(csv_dir)
    of_matches = load_openfootball_matches(openfootball_json)
    matches.extend(of_matches)
    db_matches = load_local_db_matches(local_db_json)

    # 去重: 同日同联赛同对决不重复计入
    seen = {(m["date"], m["league_code"], m["home_team"], m["away_team"]) for m in matches}
    added = 0
    for m in db_matches:
        key = (m["date"], m["league_code"], m["home_team"], m["away_team"])
        if key in seen:
            continue
        seen.add(key)
        matches.append(m)
        added += 1

    matches.sort(key=lambda m: m["date"])
    return matches


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

    # 抽取亚洲盘 — 初盘线(AHh) + Pinnacle赔率(PAHH/PAHA)
    ah_line = None
    ah_odds = None
    try:
        ah_line_str = row.get("AHh", "")
        pah_h = row.get("PAHH", "")
        pah_a = row.get("PAHA", "")
        if ah_line_str and pah_h and pah_a:
            ah_line = float(ah_line_str)
            ah_h = float(pah_h)
            ah_a = float(pah_a)
            if ah_h > 1.0 and ah_a > 1.0:
                ah_odds = {"home": ah_h, "away": ah_a}
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
        "ah_line": ah_line,
        "ah_odds": ah_odds,
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


# 规范队名别名 — API名 → CSV名
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
    # football-data.org 全名 → CSV 规范名 (复盘匹配桥接)
    "RCD Espanyol de Barcelona": "Espanol",
    "RCD Espanyol": "Espanol",
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
    "PSG": "Paris SG",
    "Västerås": "Vasteras",
    "TPS Turku": "TPS",
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
    # 2. Bundesliga
    "Dynamo Dresden": "Dresden",
    "SG Dynamo Dresden": "Dresden",
    "1. FC Nurnberg": "Nurnberg",
    "SpVgg Greuther Furth": "Greuther Furth",
    # Eredivisie
    "Ajax Amsterdam": "Ajax",
    "PSV Eindhoven": "PSV",
    "FC Utrecht": "Utrecht",
    "PEC Zwolle": "Zwolle",
    "FC Twente": "Twente",
    "SC Heerenveen": "Heerenveen",
    "FC Groningen": "Groningen",
    "Sparta Rotterdam": "Sparta Rotterdam",
    # Primeira Liga
    "Braga": "Sp Braga",
    "Sporting Braga": "Sp Braga",
    "SC Braga": "Sp Braga",
    "Vitoria Guimaraes": "Guimaraes",
    "Vitoria SC": "Guimaraes",
    "Vitoria de Guimaraes": "Guimaraes",
    "FC Porto": "Porto",
    "SL Benfica": "Benfica",
    "Sporting Lisbon": "Sp Lisbon",
    "Sporting CP": "Sp Lisbon",
    # 挪威 (CSV + openfootball)
    "Rosenborg BK": "Rosenborg",
  "Viking": "Viking FK",
    "Lillestrom SK": "Lillestrom",
    "Lillestrøm SK": "Lillestrom",
    "Molde FK": "Molde",
    "Hamarkameratene": "HamKam",
    "Aalesunds FK": "Aalesund",
    "Kristiansund BK": "Kristiansund",
    # 瑞典 (openfootball)
    "Hammarby IF": "Hammarby",
  "Elfsborg": "IF Elfsborg",
  "Vasteras": "Västerås SK",
    "BK Hacken": "Hacken",
    "BK Häcken": "Hacken",
    "IFK Goteborg": "IFK Goteborg",
    "IFK Göteborg": "IFK Goteborg",
    "GAIS Goteborg": "GAIS",
    "GAIS Göteborg": "GAIS",
    "Kalmar FF": "Kalmar",
    "Halmstads BK": "Halmstads",
    # 芬兰 (openfootball)
    "HJK Helsinki": "HJK",
    "FC Lahti": "Lahti",
    "Kuopion PS": "KuPS",
    "AC Oulu": "AC Oulu",
    "Inter Turku": "Inter Turku",
    "TPS": "TPS",
    # 巴西 (openfootball)
    "Flamengo RJ": "Flamengo",
    "CR Flamengo": "Flamengo",
    "Santos FC": "Santos",
    "Athletico Paranaense": "Athletico-PR",
    "Athletico-PR": "Athletico-PR",
    "Fortaleza EC": "Fortaleza",
    "Sao Paulo FC": "Sao Paulo",
    # 日本J1 (openfootball)
    "Kyoto Sanga FC": "Kyoto Sanga",
  "Kashiwa": "Kashiwa Reysol",
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
    # 按联赛分组球队
    league_teams: dict[str, set[str]] = defaultdict(set)
    for m in matches:
        league_teams[m["league_code"]].add(m["home_team"])
        league_teams[m["league_code"]].add(m["away_team"])

    # 每个联赛内找模糊匹配
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
    # 归一化后比较
    a_norm = a.lower().replace(" ", "").replace(".", "").replace("'", "")
    b_norm = b.lower().replace(" ", "").replace(".", "").replace("'", "")

    # 归一化后精确匹配
    if a_norm == b_norm:
        return a != b  # Only if original strings differ

    # 双向包含
    if a_norm in b_norm or b_norm in a_norm:
        return True

    # 类编辑距离: 共享长公共前缀
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
