"""
Result Fetcher v3.0

Fetches post-match results for review and ELO update.
Supports: manual JSON, odds-api.io results, API-Football fixtures (Phase 6).
"""
from __future__ import annotations

import json
import os
from typing import Any

from pipeline.data_loader import normalize_team_name


def load_results_from_json(path: str) -> list[dict]:
    """Load match results from a JSON file.

    Expected format:
    [
        {
            "home_team": "Liverpool",
            "away_team": "Arsenal",
            "home_goals": 2,
            "away_goals": 1,
            "result": "H"    ← optional, derived from goals if missing
        },
        ...
    ]
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Results file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return _normalize_results(data)


def load_results_from_text(text: str) -> list[dict]:
    """Parse results from a simple text format.

    Format (one per line):
      HomeTeam 2-1 AwayTeam
      HomeTeam 0-0 AwayTeam
      HomeTeam 1-3 AwayTeam

    Lines starting with # are comments.
    Blank lines are skipped.
    """
    results = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 尝试 "TeamA X-Y TeamB" 格式
        import re
        m = re.match(r"(.+?)\s+(\d+)\s*[-–—]\s*(\d+)\s+(.+)", line)
        if m:
            home_team = m.group(1).strip()
            home_goals = int(m.group(2))
            away_goals = int(m.group(3))
            away_team = m.group(4).strip()
            results.append({
                "home_team": home_team,
                "away_team": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
            })
            continue

        # 尝试类JSON内联格式
        try:
            obj = json.loads(line)
            if "home_team" in obj or "home" in obj:
                results.append(obj)
        except (json.JSONDecodeError, ValueError):
            pass

    return _normalize_results(results)


def try_fetch_results(date_str: str) -> list[dict] | None:
    """Try to fetch results from odds-api.io for a given date.

    Returns None if API is unavailable.
    """
    try:
        from config import ODDS_API_KEY
        if not ODDS_API_KEY:
            return None
    except Exception:
        return None

    try:
        import urllib.request
        import urllib.error

        url = (
            f"https://api.odds-api.io/v4/sports/soccer_epl/scores/"
            f"?apiKey={ODDS_API_KEY}&date={date_str}"
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for game in data.get("data", []):
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            scores = game.get("scores") or {}
            hg = scores.get("home")
            ag = scores.get("away")
            if home and away and hg is not None and ag is not None:
                results.append({
                    "home_team": home,
                    "away_team": away,
                    "home_goals": int(hg),
                    "away_goals": int(ag),
                })
        return _normalize_results(results) if results else None
    except Exception:
        return None


def _parse_apifootball_fixtures(payload: dict) -> list[dict]:
    """解析 API-Football /v3/fixtures 响应 → 结果列表 (纯函数, 可离线测试)"""
    results = []
    for fx in (payload or {}).get("response", []):
        teams = fx.get("teams") or {}
        goals = fx.get("goals") or {}
        home = (teams.get("home") or {}).get("name", "")
        away = (teams.get("away") or {}).get("name", "")
        hg = goals.get("home")
        ag = goals.get("away")
        status = (fx.get("fixture") or {}).get("status") or {}
        short = status.get("short", "")
        if not home or not away or hg is None or ag is None:
            continue
        # 只取完赛/加时/点球场次 (点球取全场比分可能为平, 以常规时间入账)
        if short not in ("FT", "AET", "PEN"):
            continue
        results.append({
            "home_team": home,
            "away_team": away,
            "home_goals": int(hg),
            "away_goals": int(ag),
        })
    return results


def try_fetch_results_apifootball(date_str: str) -> list[dict] | None:
    """从 API-Football 拉取当日赛果 (Phase 6 · 1请求/天)

    失败(未订阅/无key/网络)返回 None, 调用方回退手动赛果。
    """
    try:
        from config import FOOTBALL_RAPIDAPI_KEY
        if not FOOTBALL_RAPIDAPI_KEY:
            return None
        import httpx
        headers = {
            "x-rapidapi-key": FOOTBALL_RAPIDAPI_KEY,
            "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
        }
        with httpx.Client(timeout=20) as c:
            r = c.get(
                "https://api-football-v1.p.rapidapi.com/v3/fixtures",
                params={"date": date_str, "timezone": "Asia/Shanghai"},
                headers=headers,
            )
        if r.status_code != 200:
            print(f"  [赛果] API-Football fixtures: HTTP {r.status_code}")
            return None
        results = _parse_apifootball_fixtures(r.json())
        print(f"  [赛果] API-Football 拿到 {len(results)} 场完赛")
        return _normalize_results(results) if results else None
    except Exception as e:
        print(f"  [赛果] API-Football 拉取失败: {e}")
        return None


def _parse_footballdata_matches(payload: dict, date_str: str = "", only_finished: bool = True) -> list[dict]:
    """解析 football-data.org v4 /matches 响应 → 结果/赛程列表 (纯函数, 可离线测试)

    date_str: 只保留该 UTC 日期的场次 (接口要求 dateFrom<dateTo, 拉取窗口+1天)
    only_finished=False 时也返回未开球赛程 (含球场信息, 供预测页使用)
    """
    results = []
    for m in (payload or {}).get("matches", []):
        if only_finished and m.get("status") != "FINISHED":
            continue
        if date_str and (m.get("utcDate") or "")[:10] != date_str:
            continue
        home = (m.get("homeTeam") or {}).get("name", "")
        away = (m.get("awayTeam") or {}).get("name", "")
        if not home or not away:
            continue
        venue = (m.get("venue") or "") or "—"
        item = {
            "home_team": home,
            "away_team": away,
            "venue": venue,
        }
        score = m.get("score") or {}
        ft = score.get("fullTime") or {}
        hg = ft.get("home")
        ag = ft.get("away")
        if hg is not None and ag is not None:
            item["home_goals"] = int(hg)
            item["away_goals"] = int(ag)
        elif only_finished:
            continue
        results.append(item)
    return results


def try_fetch_fixtures_footballdata(date_str: str) -> list[dict] | None:
    """从 football-data.org v4 拉取当日赛程 (含球场, 供预测页 A 段比赛核验)

    只覆盖五大联赛等官方数据源联赛; 其他联赛返回 None → 页面显示球场未获取。
    """
    try:
        from config import FOOTBALL_DATA_API_KEY
        if not FOOTBALL_DATA_API_KEY:
            return None
        import httpx
        from datetime import datetime as _dt, timedelta as _td
        end_str = (_dt.strptime(date_str, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
        headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
        with httpx.Client(timeout=20) as c:
            r = c.get(
                "https://api.football-data.org/v4/matches",
                params={"dateFrom": date_str, "dateTo": end_str},
                headers=headers,
            )
        if r.status_code == 429:
            print("  [赛程] football-data.org 触发限流, 跳过球场采集")
            return None
        if r.status_code != 200:
            return None
        fixtures = _parse_footballdata_matches(r.json(), date_str, only_finished=False)
        return fixtures or None
    except Exception as e:
        print(f"  [赛程] football-data.org 拉取失败: {e}")
        return None


def try_fetch_results_footballdata(date_str: str) -> list[dict] | None:
    """从 football-data.org v4 拉取当日赛果 (Phase 6b · 1请求/天)

    覆盖欧洲主流联赛+部分其他地区; 失败返回 None, 调用方回退手动赛果。
    """
    try:
        from config import FOOTBALL_DATA_API_KEY
        if not FOOTBALL_DATA_API_KEY:
            return None
        import httpx
        from datetime import datetime as _dt, timedelta as _td
        # v4 要求 dateFrom < dateTo (同日返回空), 拉取窗口+1天再按UTC日期过滤
        end_str = (_dt.strptime(date_str, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
        headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
        with httpx.Client(timeout=20) as c:
            r = c.get(
                "https://api.football-data.org/v4/matches",
                params={"dateFrom": date_str, "dateTo": end_str},
                headers=headers,
            )
        if r.status_code == 429:
            print("  [赛果] football-data.org 触发限流(10请求/分钟), 本次跳过")
            return None
        if r.status_code != 200:
            print(f"  [赛果] football-data.org: HTTP {r.status_code}")
            return None
        results = _parse_footballdata_matches(r.json(), date_str)
        print(f"  [赛果] football-data.org 拿到 {len(results)} 场完赛")
        return _normalize_results(results) if results else None
    except Exception as e:
        print(f"  [赛果] football-data.org 拉取失败: {e}")
        return None


def _normalize_results(data: list[dict]) -> list[dict]:
    """Normalize and validate results data."""
    results = []
    for item in data:
        # 标准化字段名
        home = item.get("home_team") or item.get("home", "")
        away = item.get("away_team") or item.get("away", "")
        if not home or not away:
            continue

        home = normalize_team_name(home)
        away = normalize_team_name(away)

        # 缺少result时从进球推导
        if "result" not in item:
            hg = item.get("home_goals")
            ag = item.get("away_goals")
            if hg is not None and ag is not None:
                hg = int(hg)
                ag = int(ag)
                result = "H" if hg > ag else "D" if hg == ag else "A"
            else:
                result = None
        else:
            result = item["result"]
            hg = item.get("home_goals")
            ag = item.get("away_goals")

        results.append({
            "home_team": home,
            "away_team": away,
            "home_goals": int(hg) if hg is not None else None,
            "away_goals": int(ag) if ag is not None else None,
            "result": result,
        })

    return results


def match_predictions_to_results(
    predictions: list[dict],
    results: list[dict],
) -> list[dict]:
    """Match predictions to results with fuzzy team name matching.

    Returns list of matched pairs:
    [
        {
            "home_team": "...", "away_team": "...",
            "predicted": {"home_win": 0.45, "draw": 0.28, "away_win": 0.27},
            "actual": "H",
            "home_goals": 2, "away_goals": 1,
            "value": {...},  # from prediction
            "matched": True,
        },
        ...
    ]
    """
    matched = []
    unmatched_pred = []
    unmatched_res = list(results)

    for pred in predictions:
        ph = normalize_team_name(pred.get("home_team", ""))
        pa = normalize_team_name(pred.get("away_team", ""))

        found = None
        for i, res in enumerate(unmatched_res):
            rh = normalize_team_name(res.get("home_team", ""))
            ra = normalize_team_name(res.get("away_team", ""))
            if _teams_match(ph, rh) and _teams_match(pa, ra):
                found = unmatched_res.pop(i)
                break

        if found:
            model = pred.get("model", {})
            # 透传model全字段 — 维度复盘需要 over_25/over_35/btts/lambda/rho
            predicted = {
                "home_win": model.get("home_win", 0.33),
                "draw": model.get("draw", 0.34),
                "away_win": model.get("away_win", 0.33),
            }
            for k in ("over_25", "over_35", "btts",
                      "lambda_home", "lambda_away", "rho",
                      "score_distribution"):
                if model.get(k) is not None:
                    predicted[k] = model[k]
            matched.append({
                "home_team": ph,
                "away_team": pa,
                "league_code": pred.get("league_code", ""),
                "predicted": predicted,
                "actual": found["result"],
                "ah_handicap": pred.get("ah_handicap"),
                "home_goals": found.get("home_goals"),
                "away_goals": found.get("away_goals"),
                "value": pred.get("value"),
                "bayesian": pred.get("bayesian"),
                "elo_diff": pred.get("elo_diff", 0),
                "cold_start": pred.get("cold_start", False),
                "no_signal": pred.get("no_signal", False),
                "matched": True,
            })
        else:
            unmatched_pred.append(pred)

    if unmatched_pred:
        print(f"  [警告] {len(unmatched_pred)} 条预测未能匹配赛果")

    return matched


def _teams_match(a: str, b: str) -> bool:
    """模糊队名匹配 + 中英文桥接 + 重音符折叠"""
    if not a or not b:
        return False
    import unicodedata

    def _fold(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)  # ñ→n, ú→u, é→e ...
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().replace(" ", "").replace(".", "").replace("'", "")

    a_orig, b_orig = a, b
    a = _fold(a)
    b = _fold(b)
    if a == b or a in b or b in a:
        return True
    # 中英桥接: 任一方为中文名时, 用映射表翻译成英文再比 (原名大小写查表)
    try:
        from pipeline.team_names import CN_TO_EN_TEAM
        for x, y in ((a_orig, b), (b_orig, a)):
            en = CN_TO_EN_TEAM.get(x)
            if en:
                en = _fold(en)
                if en == y or en in y or y in en:
                    return True
    except Exception:
        pass
    return False
