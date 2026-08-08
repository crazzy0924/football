"""
Kambi 赔率客户端

Kambi Group 是全球最大的 B2B 体育博彩平台供应商。
以下博彩公司使用 Kambi 的赔率引擎:
  Unibet, 888sport, Betway, Paddy Power, Betfair Sportsbook,
  LeoVegas, Mr Green, Svenska Spel, DraftKings (部分市场)

通过 API-Football /odds 端点获取这些博彩公司的赔率,
取中位数作为 Kambi 共识赔率, 用于模型对比和市场分析。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from src.data.api_client import APIFootballClient, create_api_client

# ============================================================
# Kambi 平台博彩公司列表 (API-Football 中的名称)
# ============================================================

KAMBI_BOOKMAKERS = [
    "Unibet",
    "888sport",
    "Betway",
    "Paddy Power",
    "Betfair Sportsbook",
    "LeoVegas",
    "Mr Green",
    "Bethard",
    "Casumo",
    "Rizk",
    "DraftKings",
]

# 非 Kambi 博彩公司 (用于对比)
NON_KAMBI_BOOKMAKERS = [
    "Bet365",
    "William Hill",
    "Ladbrokes",
    "Coral",
    "Bwin",
    "1xBet",
    "Marathon Bet",
    "Pinnacle",           # Pinnacle 以低 margin 著称, 接近真实概率
    "SBOBET",
    "Dafabet",
]


# ============================================================
# Kambi 客户端
# ============================================================

class KambiClient:
    """Kambi 赔率数据客户端

    功能:
    - 获取指定比赛的 Kambi 博彩公司赔率
    - 计算 Kambi 共识赔率 (中位数)
    - 对比 Kambi vs 非 Kambi vs Pinnacle (sharp bookmaker)
    - 支持历史赔率查询 (用于回测)
    """

    def __init__(self) -> None:
        self._api = create_api_client()

    @property
    def is_available(self) -> bool:
        return isinstance(self._api, APIFootballClient)

    # ---- 比赛赔率 ----

    def get_kambi_odds(self, fixture_id: int) -> dict[str, Any]:
        """获取指定比赛的 Kambi 赔率

        Returns:
            {
                "fixture_id": ...,
                "kambi_consensus": {home, draw, away},  # Kambi 中位数赔率
                "kambi_implied": {home, draw, away, margin},  # 隐含概率
                "pinnacle_odds": {...},    # Pinnacle 赔率 (sharp book, 参照基准)
                "non_kambi_avg": {...},    # 非 Kambi 平均
                "bookmakers": [...],       # 原始博彩公司列表
            }
        """
        if not self.is_available:
            return {"error": "需要 API-Football (RapidAPI)", "fixture_id": fixture_id}

        try:
            odds_data = self._api._get("odds", {"fixture": fixture_id})
            bookmakers = odds_data.get("response", [])
        except Exception as e:
            return {"error": str(e), "fixture_id": fixture_id}

        if not bookmakers:
            return {"error": "该比赛无赔率数据", "fixture_id": fixture_id}

        # 解析各博彩公司赔率
        kambi_lines: list[dict] = []
        non_kambi_lines: list[dict] = []
        pinnacle_line = None

        for bm in bookmakers:
            name = bm.get("name", "")
            for bet in bm.get("bets", []):
                if bet.get("name") != "Match Winner":
                    continue
                values = bet.get("values", [])
                if len(values) < 3:
                    continue

                odds_map = {}
                for v in values:
                    odds_map[v.get("value", "")] = float(v.get("odd", 1.0))

                line = {
                    "bookmaker": name,
                    "home": odds_map.get("Home", 1.0),
                    "draw": odds_map.get("Draw", 1.0),
                    "away": odds_map.get("Away", 1.0),
                }

                if name in KAMBI_BOOKMAKERS:
                    kambi_lines.append(line)
                elif name == "Pinnacle":
                    pinnacle_line = line
                else:
                    non_kambi_lines.append(line)
                break

        # Kambi 共识赔率 (中位数)
        kambi_consensus = None
        if kambi_lines:
            homes = sorted(l["home"] for l in kambi_lines)
            draws = sorted(l["draw"] for l in kambi_lines)
            aways = sorted(l["away"] for l in kambi_lines)
            mid = len(kambi_lines) // 2
            kambi_consensus = {
                "home": round(homes[mid], 2),
                "draw": round(draws[mid], 2),
                "away": round(aways[mid], 2),
                "bookmaker_count": len(kambi_lines),
            }

        # 非 Kambi 平均
        non_kambi_avg = None
        if non_kambi_lines:
            non_kambi_avg = {
                "home": round(sum(l["home"] for l in non_kambi_lines) / len(non_kambi_lines), 2),
                "draw": round(sum(l["draw"] for l in non_kambi_lines) / len(non_kambi_lines), 2),
                "away": round(sum(l["away"] for l in non_kambi_lines) / len(non_kambi_lines), 2),
                "bookmaker_count": len(non_kambi_lines),
            }

        # 隐含概率计算
        from src.models.odds_analyzer import calculate_implied_probability

        kambi_implied = None
        if kambi_consensus:
            imp = calculate_implied_probability(
                kambi_consensus["home"], kambi_consensus["draw"],
                kambi_consensus["away"], method="shin"
            )
            kambi_implied = {
                "home": imp.home, "draw": imp.draw, "away": imp.away,
                "margin": imp.margin,
            }

        return {
            "fixture_id": fixture_id,
            "kambi_consensus": kambi_consensus,
            "kambi_implied": kambi_implied,
            "pinnacle": pinnacle_line,
            "non_kambi_avg": non_kambi_avg,
            "kambi_bookmakers": [l["bookmaker"] for l in kambi_lines],
            "source": "API-Football",
        }

    # ---- 回顾模式 ----

    def get_yesterday_matches(self, league_code: str = "PL") -> list[dict]:
        """获取昨天的已完赛比赛 (含实际结果)

        Returns:
            [{fixture_id, home_team, away_team, home_goals, away_goals, ...}]
        """
        if not self.is_available:
            return []

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            data = self._api._get("fixtures", {"date": yesterday, "league": _league_id(league_code)})
            fixtures = data.get("response", [])
        except Exception as e:
            logger.error(f"获取昨日比赛失败: {e}")
            return []

        matches = []
        for f in fixtures:
            fixt = f.get("fixture", {})
            if fixt.get("status", {}).get("short") != "FT":
                continue  # 只取完赛的

            goals = f.get("goals", {})
            teams = f.get("teams", {})

            matches.append({
                "fixture_id": fixt["id"],
                "date": fixt.get("date", "")[:10],
                "home_team": teams.get("home", {}).get("name", ""),
                "away_team": teams.get("away", {}).get("name", ""),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "result": ("H" if (goals.get("home") or 0) > (goals.get("away") or 0)
                           else "A" if (goals.get("away") or 0) > (goals.get("home") or 0)
                           else "D"),
                "competition": f.get("league", {}).get("name", ""),
            })
        return matches


def _league_id(code: str) -> int:
    """联赛代码 → API-Football ID"""
    mapping = {"PL": 39, "PD": 140, "BL1": 78, "SA": 135, "FL1": 61, "CL": 2}
    return mapping.get(code, 39)
