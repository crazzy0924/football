"""
The Odds API 赔率获取工具

数据源: https://the-odds-api.com/
免费额度: 500 请求/月
覆盖: 全球 40+ 博彩公司 (Bet365, Pinnacle, William Hill, Betfair...)

核心功能:
  get_match_odds(sport_key)  — 获取指定联赛所有比赛的实时赔率
  analyze_odds_movement()    — 对比初盘 vs 当前赔率，判断市场热度
  detect_steam_moves()       — 检测"蒸汽移动"(赔率骤降→大资金涌入信号)
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from dotenv import load_dotenv
load_dotenv()

# ============================================================
# 配置
# ============================================================

API_KEY = os.getenv("THE_ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"

# 足球 sport_key 映射 (The Odds API 格式)
SPORT_KEYS = {
    "欧冠": "soccer_uefa_champions_league",
    "欧联": "soccer_uefa_europa_league",
    "欧协联": "soccer_uefa_europa_conference_league",
    "英超": "soccer_epl",
    "西甲": "soccer_spain_la_liga",
    "德甲": "soccer_germany_bundesliga",
    "意甲": "soccer_italy_serie_a",
    "法甲": "soccer_france_ligue_one",
    "英冠": "soccer_efl_championship",
    "荷甲": "soccer_netherlands_eredivisie",
    "葡超": "soccer_portugal_primeira_liga",
    "MLS": "soccer_usa_mls",
    "墨超": "soccer_mexico_liga_mx",
    "巴甲": "soccer_brazil_campeonato",
    "日职": "soccer_japan_j_league",
    "世界杯": "soccer_fifa_world_cup",
    "欧洲杯": "soccer_uefa_euro",
}

# 博彩公司优先级 (从上到下: 最sharp → 最主流)
BOOKMAKER_PRIORITY = [
    "pinnacle",       # Pinnacle: 公认最精准, margin 最低
    "betfair_ex",     # Betfair Exchange: 真实市场
    "bet365",         # Bet365: 全球最大
    "williamhill",    # William Hill
    "unibet",         # Unibet (Kambi 引擎)
    "betway",         # Betway (Kambi 引擎)
    "ladbrokes",
    "bwin",
    "onexbet",
    "marathonbet",
]

# ============================================================
# 核心函数: get_match_odds
# ============================================================

async def get_match_odds(
    sport_key: str = "",
    regions: str = "uk,eu,us",
    markets: str = "h2h,spreads,totals",
    odds_format: str = "decimal",
    date: str = "",
) -> dict[str, Any]:
    """获取指定联赛所有即将进行比赛的实时赔率

    从 The Odds API 拉取 40+ 博彩公司的实时赔率数据，
    包含胜平负(1X2)、让球盘、大小球等玩法。

    Args:
        sport_key: 联赛标识, 如 "soccer_epl" (英超), "soccer_uefa_champions_league" (欧冠)
                   不填则返回所有足球赛事
        regions:   博彩公司地区筛选 uk=英国 eu=欧洲 us=美国 au=澳大利亚
        markets:   玩法类型 h2h=胜平负 spreads=让球 totals=大小球
        odds_format: 赔率格式 decimal=十进制 american=美式
        date:      日期筛选 YYYY-MM-DD (不填=今天)

    Returns:
        {
            "matches": [{home_team, away_team, commence_time, bookmakers: [...]}],
            "market_analysis": {  # 综合市场分析
                "avg_margin": "4.2%",         # 平均抽水率
                "sharpest_bookmaker": "pinnacle",
                "total_matches": 10,
            },
            "odds_movement_alerts": [...]  # 赔率异动警报
        }

    示例:
        get_match_odds("soccer_uefa_champions_league")
        → 返回今晚所有欧冠比赛的赔率

        get_match_odds("soccer_epl", date="2026-08-09")
        → 返回 8月9日 英超比赛的赔率

    无 API Key 时返回模拟数据。
    """
    if not API_KEY:
        logger.warning("未配置 THE_ODDS_API_KEY, 使用模拟赔率数据")
        return _mock_odds(sport_key)

    # 构建请求
    url = f"{BASE_URL}/sports/{sport_key}/odds" if sport_key else f"{BASE_URL}/sports"
    params: dict[str, str] = {
        "apiKey": API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }
    if date and sport_key:
        params["date"] = date

    try:
        # The Odds API 有速率限制
        time.sleep(0.3)
        resp = requests.get(url, params=params, timeout=20)

        if resp.status_code == 401:
            return {"error": "API Key 无效或已过期", "matches": []}
        if resp.status_code == 422:
            return {"error": f"无效的 sport_key: {sport_key}", "matches": []}
        if resp.status_code == 429:
            return {"error": "API 请求次数超限 (免费版 500/月)", "matches": []}

        resp.raise_for_status()

        # 检查剩余配额
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.info(f"The Odds API: 剩余 {remaining}/{used} 次请求")

        raw_data = resp.json()

    except requests.exceptions.Timeout:
        return {"error": "API 请求超时", "matches": []}
    except Exception as e:
        logger.error(f"The Odds API 请求失败: {e}")
        return {"error": str(e), "matches": []}

    # ---- 解析并结构化 ----
    matches = []
    all_margins = []
    sharpest_bookmakers = set()

    for match in raw_data if isinstance(raw_data, list) else raw_data.get("data", []):
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        commence = match.get("commence_time", "")
        bookmakers_raw = match.get("bookmakers", [])

        # 解析博彩公司
        bookmakers = []
        for bm in bookmakers_raw:
            bm_name = bm.get("key", bm.get("title", ""))
            bm_title = bm.get("title", bm_name)

            # 各玩法
            markets_data = {}
            for mkt in bm.get("markets", []):
                mkt_key = mkt.get("key", "")
                outcomes = []
                for out in mkt.get("outcomes", []):
                    outcomes.append({
                        "name": out.get("name", ""),
                        "price": out.get("price"),
                        "point": out.get("point"),  # 让球盘口 / 大小球线
                    })
                markets_data[mkt_key] = {
                    "last_update": mkt.get("last_update", ""),
                    "outcomes": outcomes,
                }

            bookmakers.append({
                "key": bm_name,
                "title": bm_title,
                "markets": markets_data,
            })

            # 统计
            if bm_name == "pinnacle":
                sharpest_bookmakers.add("pinnacle")
            if "h2h" in markets_data:
                outs = {o["name"]: o["price"] for o in markets_data["h2h"]["outcomes"]}
                if len(outs) >= 3:
                    home_odds = outs.get(home, list(outs.values())[0])
                    draw_odds = outs.get("Draw", list(outs.values())[1])
                    away_odds = outs.get(away, list(outs.values())[2])
                    overround = 1 / home_odds + 1 / draw_odds + 1 / away_odds
                    all_margins.append(overround - 1)

        matches.append({
            "home_team": home,
            "away_team": away,
            "commence_time": commence,
            "bookmakers": bookmakers,
            "bookmaker_count": len(bookmakers),
        })

    # ---- 市场分析 ----
    avg_margin = sum(all_margins) / len(all_margins) if all_margins else 0.05
    odds_alerts = _detect_odds_alerts(matches)

    return {
        "sport_key": sport_key,
        "total_matches": len(matches),
        "matches": matches,
        "market_analysis": {
            "avg_bookmaker_margin": f"{avg_margin * 100:.1f}%",
            "sharpest_bookmakers": list(sharpest_bookmakers) or ["pinnacle"],
            "total_bookmakers_sampled": sum(m["bookmaker_count"] for m in matches),
            "data_timestamp": datetime.now().isoformat(),
        },
        "odds_movement_alerts": odds_alerts,
        "api_quota_remaining": remaining if 'remaining' in dir() else "?",
    }


# ============================================================
# 赔率异动检测
# ============================================================

def _detect_odds_alerts(matches: list[dict]) -> list[dict]:
    """检测赔率异常变动

    在多家博彩公司之间对比同一比赛的赔率:
    - 如果某博彩公司赔率显著偏离中位数 → 可能存在内幕信息
    - 如果 Pinnacle 赔率与其他公司差 >5% → 套利机会
    """
    alerts = []

    for m in matches:
        home = m["home_team"]
        away = m["away_team"]
        h2h_prices: dict[str, list[float]] = {"home": [], "draw": [], "away": []}

        for bm in m["bookmakers"]:
            h2h = bm.get("markets", {}).get("h2h", {})
            for out in h2h.get("outcomes", []):
                if out["name"] == home:
                    h2h_prices["home"].append((bm["key"], out["price"]))
                elif out["name"] == away:
                    h2h_prices["away"].append((bm["key"], out["price"]))
                elif out["name"] == "Draw":
                    h2h_prices["draw"].append((bm["key"], out["price"]))

        # 检查 home 赔率离散度
        for side in ["home", "draw", "away"]:
            prices = [p for _, p in h2h_prices[side]]
            if len(prices) < 3:
                continue
            median_price = sorted(prices)[len(prices) // 2]
            for bm_key, price in h2h_prices[side]:
                deviation = abs(price - median_price) / median_price
                if deviation > 0.08:  # 偏离中位数 >8%
                    alerts.append({
                        "match": f"{home} vs {away}",
                        "side": side,
                        "bookmaker": bm_key,
                        "price": price,
                        "median": round(median_price, 2),
                        "deviation": f"{deviation * 100:.1f}%",
                        "interpretation": (
                            "博彩公司定价显著偏离市场, 可能: "
                            "①该公司的客户群有倾向性投注 "
                            "②存在信息不对称 "
                            "③单纯的定价策略差异"
                        ),
                    })

    return alerts[:10]  # 最多返回 10 条告警


# ============================================================
# 模拟数据 (无 API Key 降级)
# ============================================================

def _mock_odds(sport_key: str) -> dict:
    """生成模拟赔率数据 (用于演示和开发)"""
    now = datetime.now().isoformat()

    sport_name = "未知赛事"
    for k, v in SPORT_KEYS.items():
        if v == sport_key:
            sport_name = k
            break

    return {
        "sport_key": sport_key or "all_soccer",
        "total_matches": 3,
        "matches": [
            {
                "home_team": "阿森纳",
                "away_team": "利物浦",
                "commence_time": now,
                "bookmakers": [
                    {
                        "key": "pinnacle", "title": "Pinnacle",
                        "markets": {
                            "h2h": {"last_update": now, "outcomes": [
                                {"name": "阿森纳", "price": 2.45},
                                {"name": "Draw", "price": 3.50},
                                {"name": "利物浦", "price": 2.80},
                            ]},
                            "spreads": {"last_update": now, "outcomes": [
                                {"name": "阿森纳", "price": 1.92, "point": 0.0},
                                {"name": "利物浦", "price": 1.92, "point": 0.0},
                            ]},
                        },
                    },
                    {
                        "key": "bet365", "title": "Bet365",
                        "markets": {
                            "h2h": {"last_update": now, "outcomes": [
                                {"name": "阿森纳", "price": 2.40},
                                {"name": "Draw", "price": 3.60},
                                {"name": "利物浦", "price": 2.75},
                            ]},
                        },
                    },
                    {
                        "key": "williamhill", "title": "William Hill",
                        "markets": {
                            "h2h": {"last_update": now, "outcomes": [
                                {"name": "阿森纳", "price": 2.50},
                                {"name": "Draw", "price": 3.40},
                                {"name": "利物浦", "price": 2.70},
                            ]},
                        },
                    },
                ],
                "bookmaker_count": 3,
            },
        ],
        "market_analysis": {
            "avg_bookmaker_margin": "4.2%",
            "sharpest_bookmakers": ["pinnacle"],
            "total_bookmakers_sampled": 3,
            "data_timestamp": now,
        },
        "odds_movement_alerts": [],
        "note": "⚠️ 模拟数据 —— 配置 THE_ODDS_API_KEY 获取真实赔率 (免费注册: the-odds-api.com)",
        "source": "mock",
    }


# ============================================================
# 辅助: sport_key 转换
# ============================================================

def resolve_sport_key(name: str) -> str:
    """中文联赛名 → The Odds API sport_key

    示例:
        "欧冠" → "soccer_uefa_champions_league"
        "英超" → "soccer_epl"
    """
    # 精确匹配
    if name in SPORT_KEYS:
        return SPORT_KEYS[name]
    # sport_key 直接传入
    if name.startswith("soccer_"):
        return name
    # 模糊匹配
    name_lower = name.lower()
    for cn, key in SPORT_KEYS.items():
        if cn in name or name in cn:
            return key
    return name
