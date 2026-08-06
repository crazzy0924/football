"""
实时赔率工具 — The Odds API + 缓存 + 降级

数据来源: https://the-odds-api.com/v4
免费额度: 500 请求/月
缓存策略: 同一比赛3分钟内不重复请求
降级策略: API不可用时返回本地模拟数据
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY", os.getenv("THE_ODDS_API_KEY", ""))
BASE_URL = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "odds_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 内存缓存: {cache_key: (timestamp, data)}
_MEMORY_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 180  # 通用缓存3分钟
_TODAY_CACHE_TTL = 1800  # 当天赛程缓存30分钟

# ============================================================
# 缓存层
# ============================================================

def _cache_key(sport: str, regions: str, markets: str) -> str:
    return f"{sport}_{regions}_{markets}"

def _cache_get(key: str) -> Any | None:
    """先查内存, 再查本地文件"""
    # 内存
    if key in _MEMORY_CACHE:
        ts, data = _MEMORY_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            logger.debug(f"内存缓存命中: {key}")
            return data

    # 文件
    fpath = CACHE_DIR / f"{key}.json"
    if fpath.exists():
        age = time.time() - fpath.stat().st_mtime
        if age < _CACHE_TTL:
            try:
                data = json.loads(fpath.read_text())
                _MEMORY_CACHE[key] = (time.time(), data)
                logger.debug(f"文件缓存命中: {key}")
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return None

def _cache_set(key: str, data: Any) -> None:
    _MEMORY_CACHE[key] = (time.time(), data)
    fpath = CACHE_DIR / f"{key}.json"
    try:
        fpath.write_text(json.dumps(data, ensure_ascii=False, default=str))
    except OSError:
        pass

# ============================================================
# 核心函数
# ============================================================

async def get_live_odds(
    sport_key: str = "upcoming",
    regions: str = "uk,eu",
    markets: str = "h2h,spreads,totals",
    odds_format: str = "decimal",
) -> dict[str, Any]:
    """获取实时赔率 (带缓存)

    Args:
        sport_key: 联赛标识, 如 "soccer_epl", "upcoming"=所有即将比赛
        regions:   博彩公司地区
        markets:   玩法类型
        odds_format: 赔率格式

    Returns:
        {
            "matches": [...],
            "cached": true/false,
            "source": "The Odds API" / "模拟数据(降级)"
        }
    """
    cache_k = _cache_key(sport_key, regions, markets)

    # 查缓存
    cached = _cache_get(cache_k)
    if cached is not None:
        cached["cached"] = True
        return cached

    # 无API Key → 降级
    if not API_KEY:
        logger.warning("未配置 ODDS_API_KEY, 使用模拟数据")
        data = _mock_live_odds(sport_key)
        data["source"] = "模拟数据(降级)"
        data["cached"] = False
        return data

    # 调用 API
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }

    try:
        time.sleep(0.3)  # 速率限制
        resp = requests.get(url, params=params, timeout=20)

        if resp.status_code == 401:
            return {"error": "API Key 无效", "matches": [], "source": "API错误"}
        if resp.status_code == 429:
            return {"error": "请求超限 (免费版500/月)", "matches": [], "source": "API限流"}
        if resp.status_code == 422:
            # 可能是无效sport_key, 尝试降级
            logger.warning(f"无效sport_key: {sport_key}, 尝试降级")
            data = _mock_live_odds(sport_key)
            data["source"] = "模拟数据(降级:sport_key无效)"
            return data

        resp.raise_for_status()
        data = resp.json()

        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info(f"The Odds API: 剩余 {remaining} 次请求")

        result = {
            "matches": _parse_matches(data),
            "total": len(data) if isinstance(data, list) else 0,
            "source": "The Odds API",
            "api_remaining": remaining,
            "cached": False,
            "fetched_at": datetime.now().isoformat(),
        }

        # 写缓存
        _cache_set(cache_k, result)
        return result

    except requests.exceptions.Timeout:
        logger.error("API 超时, 降级模拟数据")
        data = _mock_live_odds(sport_key)
        data["source"] = "模拟数据(超时降级)"
        return data
    except Exception as e:
        logger.error(f"API 错误: {e}, 降级模拟数据")
        data = _mock_live_odds(sport_key)
        data["source"] = f"模拟数据(错误降级: {str(e)[:50]})"
        return data


def _parse_matches(raw: list | dict) -> list[dict]:
    """解析API返回的比赛数据"""
    matches = []
    items = raw if isinstance(raw, list) else raw.get("data", [])

    for m in items:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        commence = m.get("commence_time", "")

        bookmakers = []
        for bm in m.get("bookmakers", []):
            bm_data = {"key": bm.get("key", ""), "title": bm.get("title", ""), "markets": {}}
            for mkt in bm.get("markets", []):
                outcomes = [{"name": o["name"], "price": o.get("price"), "point": o.get("point")}
                            for o in mkt.get("outcomes", [])]
                bm_data["markets"][mkt["key"]] = {"outcomes": outcomes, "last_update": mkt.get("last_update", "")}
            bookmakers.append(bm_data)

        matches.append({
            "home_team": home, "away_team": away, "commence_time": commence,
            "bookmakers": bookmakers, "bookmaker_count": len(bookmakers),
        })

    return matches


# ============================================================
# 当天所有比赛
# ============================================================

async def get_today_odds_matches(
    sport_key: str = "upcoming",
    regions: str = "uk,eu,hk",
) -> dict[str, Any]:
    """获取今天所有开盘比赛及初盘赔率

    当用户问"今天有什么比赛"或"今天开盘的比赛"时调用此函数。

    Args:
        sport_key: "upcoming"=所有即将比赛, 或指定联赛
        regions:   博彩公司地区 uk=英国 eu=欧洲 hk=香港(亚洲)

    Returns:
        {
            "date": "2026-08-06",
            "total": 13,
            "cached": true/false,
            "cache_time": "16:30",
            "by_league": {"欧联": [...], "欧协联": [...]},
            "matches": [{home, away, league, kickoff, odds_1x2, odds_ah, odds_ou}, ...],
            "source": "The Odds API" / "模拟数据"
        }
    """
    cache_k = f"today_{sport_key}_{regions}"

    # 查缓存 (30分钟)
    if cache_k in _MEMORY_CACHE:
        ts, data = _MEMORY_CACHE[cache_k]
        if time.time() - ts < _TODAY_CACHE_TTL:
            logger.debug(f"赛程缓存命中 ({(time.time()-ts)/60:.0f}分钟前)")
            data["cached"] = True
            data["cache_time"] = datetime.fromtimestamp(ts).strftime("%H:%M")
            return data

    fpath = CACHE_DIR / f"{cache_k}.json"
    if fpath.exists():
        age = time.time() - fpath.stat().st_mtime
        if age < _TODAY_CACHE_TTL:
            try:
                data = json.loads(fpath.read_text())
                _MEMORY_CACHE[cache_k] = (time.time(), data)
                data["cached"] = True
                data["cache_time"] = datetime.fromtimestamp(fpath.stat().st_mtime).strftime("%H:%M")
                logger.debug(f"赛程文件缓存命中 ({(age)/60:.0f}分钟前)")
                return data
            except (json.JSONDecodeError, OSError):
                pass

    # 无 API Key → 降级热门联赛模拟数据
    if not API_KEY:
        logger.warning("未配置 ODDS_API_KEY, 使用模拟赛程")
        data = _mock_today_matches()
        data["source"] = "模拟数据(降级: 热门联赛)"
        return data

    # 调用 API
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": regions,
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
    }

    try:
        time.sleep(0.3)
        resp = requests.get(url, params=params, timeout=20)

        if resp.status_code in (401, 429, 422):
            logger.warning(f"API 状态 {resp.status_code}, 降级")
            data = _mock_today_matches()
            data["source"] = f"模拟数据(API {resp.status_code})"
            return data

        resp.raise_for_status()
        raw = resp.json()
        matches_list = raw if isinstance(raw, list) else raw.get("data", [])

        matches = []
        by_league: dict[str, list] = {}

        for m in matches_list:
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            kickoff = m.get("commence_time", "")
            sport = m.get("sport_key", "")

            # 提取联赛名
            league_name = sport.replace("soccer_", "").replace("_", " ").title()

            # 提取初盘赔率 (取第一家博彩公司作参考)
            bookmakers = m.get("bookmakers", [])
            opening = {}
            current = {}
            ah_line = None
            ou_line = None

            for bm in bookmakers[:5]:
                bm_name = bm.get("key", "")
                for mkt in bm.get("markets", []):
                    outcomes = mkt.get("outcomes", [])
                    if mkt["key"] == "h2h" and len(outcomes) >= 3:
                        odds_v = {o["name"]: o["price"] for o in outcomes}
                        if bm_name == "pinnacle":
                            current = odds_v
                        if not opening:
                            opening = odds_v
                    if mkt["key"] == "spreads" and outcomes:
                        ah_line = {"point": outcomes[0].get("point"), "home": outcomes[0].get("price"),
                                   "away": outcomes[1].get("price") if len(outcomes) > 1 else None}
                    if mkt["key"] == "totals" and outcomes:
                        ou_line = {"point": outcomes[0].get("point"), "over": outcomes[0].get("price"),
                                   "under": outcomes[1].get("price") if len(outcomes) > 1 else None}

            match_data = {
                "home_team": home,
                "away_team": away,
                "league": league_name,
                "kickoff": kickoff,
                "opening_odds": opening,
                "pinnacle_odds": current,
                "asian_handicap": ah_line,
                "over_under": ou_line,
                "bookmaker_count": len(bookmakers),
            }
            matches.append(match_data)
            by_league.setdefault(league_name, []).append(match_data)

        remaining = resp.headers.get("x-requests-remaining", "?")
        now = datetime.now()
        result = {
            "date": now.strftime("%Y-%m-%d"),
            "total": len(matches),
            "by_league": by_league,
            "matches": matches,
            "source": "The Odds API",
            "api_remaining": remaining,
            "cached": False,
            "cache_time": now.strftime("%H:%M"),
        }
        _MEMORY_CACHE[cache_k] = (time.time(), result)
        fpath = CACHE_DIR / f"{cache_k}.json"
        try:
            fpath.write_text(json.dumps(result, ensure_ascii=False, default=str))
        except OSError:
            pass
        return result

    except Exception as e:
        logger.error(f"获取今日比赛失败: {e}, 降级")
        data = _mock_today_matches()
        data["source"] = f"模拟数据(错误: {str(e)[:40]})"
        return data


def _mock_today_matches() -> dict[str, Any]:
    """生成当日模拟赛程 (热门联赛)"""
    today = datetime.now().strftime("%Y-%m-%d")
    mock_matches = [
        {"home_team": "本菲卡", "away_team": "哈茨", "league": "欧联资格赛",
         "kickoff": f"{today}T20:00:00Z",
         "opening_odds": {"本菲卡": 1.07, "Draw": 10.90, "哈茨": 26.95},
         "pinnacle_odds": {"本菲卡": 1.07, "Draw": 10.90, "哈茨": 26.95},
         "asian_handicap": {"point": -2.5}, "over_under": {"point": 3.5, "over": 1.45, "under": 2.60},
         "bookmaker_count": 20},
        {"home_team": "萨尔茨堡红牛", "away_team": "帕福斯", "league": "欧联资格赛",
         "kickoff": f"{today}T17:00:00Z",
         "opening_odds": {"萨尔茨堡红牛": 1.50, "Draw": 4.20, "帕福斯": 5.40},
         "pinnacle_odds": {"萨尔茨堡红牛": 1.48, "Draw": 4.30, "帕福斯": 5.68},
         "asian_handicap": {"point": -1.0}, "over_under": {"point": 2.5, "over": 1.60, "under": 2.15},
         "bookmaker_count": 18},
        {"home_team": "阿贾克斯", "away_team": "谢尔伯恩", "league": "欧协联资格赛",
         "kickoff": f"{today}T18:30:00Z",
         "opening_odds": {"阿贾克斯": 1.10, "Draw": 8.50, "谢尔伯恩": 21.00},
         "pinnacle_odds": {"阿贾克斯": 1.09, "Draw": 9.00, "谢尔伯恩": 23.00},
         "asian_handicap": {"point": -2.0}, "over_under": {"point": 3.5, "over": 1.40, "under": 2.70},
         "bookmaker_count": 15},
        {"home_team": "布拉加", "away_team": "明斯克迪纳摩", "league": "欧协联资格赛",
         "kickoff": f"{today}T19:00:00Z",
         "opening_odds": {"布拉加": 1.25, "Draw": 5.50, "明斯克迪纳摩": 11.00},
         "pinnacle_odds": {"布拉加": 1.24, "Draw": 5.70, "明斯克迪纳摩": 12.00},
         "asian_handicap": {"point": -1.5}, "over_under": {"point": 2.5, "over": 1.55, "under": 2.30},
         "bookmaker_count": 14},
        {"home_team": "拉科夫", "away_team": "哈马比", "league": "欧协联资格赛",
         "kickoff": f"{today}T17:00:00Z",
         "opening_odds": {"拉科夫": 2.27, "Draw": 3.40, "哈马比": 3.38},
         "pinnacle_odds": {"拉科夫": 2.10, "Draw": 3.14, "哈马比": 3.28},
         "asian_handicap": {"point": -0.25}, "over_under": {"point": 2.5, "over": 1.90, "under": 1.85},
         "bookmaker_count": 12},
        {"home_team": "谢里夫", "away_team": "圣加仑", "league": "欧协联资格赛",
         "kickoff": f"{today}T17:00:00Z",
         "opening_odds": {"谢里夫": 3.90, "Draw": 3.40, "圣加仑": 2.05},
         "pinnacle_odds": {"谢里夫": 3.39, "Draw": 3.39, "圣加仑": 1.99},
         "asian_handicap": {"point": 0.5}, "over_under": {"point": 2.5, "over": 1.88, "under": 1.86},
         "bookmaker_count": 10},
    ]
    by_league = {}
    for m in mock_matches:
        by_league.setdefault(m["league"], []).append(m)

    return {
        "date": today,
        "total": len(mock_matches),
        "by_league": by_league,
        "matches": mock_matches,
        "source": "模拟数据(热门联赛)",
        "note": "配置 ODDS_API_KEY 获取完整真实赛程 (免费: the-odds-api.com)",
    }


# ============================================================
# 模拟数据 (降级)
# ============================================================

def _mock_live_odds(sport_key: str) -> dict[str, Any]:
    """生成模拟赔率"""
    sport_name = sport_key.replace("soccer_", "").replace("_", " ").title()
    return {
        "matches": [
            {
                "home_team": "主队A", "away_team": "客队B",
                "commence_time": (datetime.now() + timedelta(hours=3)).isoformat(),
                "bookmakers": [
                    {"key": "pinnacle", "title": "Pinnacle",
                     "markets": {"h2h": {"outcomes": [
                         {"name": "主队A", "price": 2.10},
                         {"name": "Draw", "price": 3.40},
                         {"name": "客队B", "price": 3.20}]}}},
                    {"key": "bet365", "title": "Bet365",
                     "markets": {"h2h": {"outcomes": [
                         {"name": "主队A", "price": 2.05},
                         {"name": "Draw", "price": 3.50},
                         {"name": "客队B", "price": 3.10}]}}},
                ],
                "bookmaker_count": 2,
            },
        ],
        "total": 1,
        "source": "模拟数据(降级)",
        "cached": False,
        "note": f"配置 ODDS_API_KEY 获取 {sport_name} 真实赔率 (免费注册: the-odds-api.com)",
    }
