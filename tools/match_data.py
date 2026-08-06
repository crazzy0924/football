"""
比赛基础数据工具 — API-Football v3

数据来源: https://api-football-v1.p.rapidapi.com/v3/
免费额度: RapidAPI 基础计划 ~100 请求/天
降级策略: API不可用时返回静态模拟数据
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY", os.getenv("FOOTBALL_RAPIDAPI_KEY", ""))
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
} if API_KEY else {}

# 常用联赛 ID
LEAGUE_IDS = {
    "英超": 39, "西甲": 140, "德甲": 78, "意甲": 135, "法甲": 61,
    "欧冠": 2, "欧联": 3, "欧协联": 848,
    "英冠": 40, "荷甲": 88, "葡超": 94, "MLS": 253, "墨超": 262, "巴甲": 71,
}

_RATE_LIMIT = 0.35  # 3 req/s


def _get(endpoint: str, params: dict | None = None) -> dict:
    """发送 API 请求 (带速率限制)"""
    if not HEADERS.get("x-rapidapi-key"):
        raise RuntimeError("未配置 API_FOOTBALL_KEY")

    time.sleep(_RATE_LIMIT)
    resp = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                        params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ============================================================
# 赛程 & 实时比分
# ============================================================

async def get_fixtures(
    league_id: int | str | None = None,
    date: str | None = None,
    season: int | None = None,
    status: str = "NS",  # NS=未开始, LIVE=进行中, FT=已结束
) -> dict[str, Any]:
    """获取赛程/比分

    Args:
        league_id: 联赛ID (支持中文名自动转换, 如 "英超"→39)
        date:      YYYY-MM-DD, 不传=今天
        season:    赛季年份
        status:    NS/LIVE/FT

    Returns:
        {"matches": [...], "total": N, "source": "API-Football" / "模拟数据"}
    """
    # 中文名→ID
    if isinstance(league_id, str) and league_id in LEAGUE_IDS:
        league_id = LEAGUE_IDS[league_id]

    params: dict[str, Any] = {}
    if league_id:
        params["league"] = league_id
    if date:
        params["date"] = date
    if season:
        params["season"] = season
    if not date and not season:
        params["date"] = datetime.now().strftime("%Y-%m-%d")

    if not API_KEY:
        logger.warning("无 API Key, 使用模拟赛程")
        return {
            "matches": _mock_fixtures(),
            "total": len(_mock_fixtures()),
            "source": "模拟数据(降级)",
        }

    try:
        data = _get("fixtures", params)
        fixtures = data.get("response", [])

        matches = []
        for f in fixtures:
            fixt = f.get("fixture", {})
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            league = f.get("league", {})

            matches.append({
                "id": fixt.get("id"),
                "date": fixt.get("date", "")[:19].replace("T", " "),
                "status": fixt.get("status", {}).get("short", "?"),
                "elapsed": fixt.get("status", {}).get("elapsed", 0),
                "home_team": teams.get("home", {}).get("name", ""),
                "away_team": teams.get("away", {}).get("name", ""),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "competition": league.get("name", ""),
            })

        return {
            "matches": matches,
            "total": len(matches),
            "source": "API-Football",
        }
    except RuntimeError:
        return {"matches": _mock_fixtures(), "total": 0, "source": "模拟数据(无API Key)"}
    except Exception as e:
        logger.error(f"API错误: {e}")
        return {"matches": _mock_fixtures(), "total": 0, "source": f"模拟数据(错误: {str(e)[:40]})"}


async def get_team_stats(team_id: int, league_id: int | None = None) -> dict[str, Any]:
    """获取球队近期战绩

    Args:
        team_id:   球队ID
        league_id: 联赛ID (可选)

    Returns:
        {"form": "WDLWW", "goals_for_avg": 1.8, ...}
    """
    if not API_KEY:
        return _mock_team_stats(team_id)

    params: dict[str, Any] = {"team": team_id, "last": 10}
    if league_id:
        params["league"] = league_id

    try:
        data = _get("fixtures", params)
        fixtures = data.get("response", [])

        form = ""
        goals_for = goals_against = 0
        wins = draws = losses = 0

        for f in fixtures:
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            is_home = teams.get("home", {}).get("id") == team_id
            gf = goals.get("home") if is_home else goals.get("away")
            ga = goals.get("away") if is_home else goals.get("home")
            gf = gf or 0; ga = ga or 0

            goals_for += gf; goals_against += ga
            if gf > ga: form += "W"; wins += 1
            elif gf < ga: form += "L"; losses += 1
            else: form += "D"; draws += 1

        n = len(fixtures) or 1

        return {
            "team_id": team_id,
            "matches": n,
            "form": form,
            "wins": wins, "draws": draws, "losses": losses,
            "goals_for_avg": round(goals_for / n, 2),
            "goals_against_avg": round(goals_against / n, 2),
            "source": "API-Football",
        }
    except Exception as e:
        logger.error(f"API错误: {e}")
        return _mock_team_stats(team_id)


def _mock_fixtures() -> list[dict]:
    """模拟赛程"""
    return [
        {"id": 1001, "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
         "status": "NS", "home_team": "主队A", "away_team": "客队B",
         "home_goals": None, "away_goals": None, "competition": "模拟联赛"},
    ]


def _mock_team_stats(team_id: int) -> dict:
    """模拟球队数据"""
    return {
        "team_id": team_id,
        "matches": 5, "form": "WDLWW", "wins": 3, "draws": 1, "losses": 1,
        "goals_for_avg": 1.6, "goals_against_avg": 1.0,
        "source": "模拟数据(降级)",
    }
