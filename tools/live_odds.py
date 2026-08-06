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
_CACHE_TTL = 180  # 3分钟

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
