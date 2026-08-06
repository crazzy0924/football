#!/usr/bin/env python3
"""
足球分析智能体 —— 独立 Agent 脚本
================================================================
使用 Anthropic Claude API + Function Calling 实现:

  工具 1: get_live_scores       → 实时比分 & 比赛状态 (API-Football)
  工具 2: query_head_to_head    → 历史交锋数据查询
  工具 3: calculate_recent_xg   → 近 N 场场均 xG (预期进球)
  工具 4: generate_radar_chart   → 球队能力雷达图 (matplotlib)

用法:
    python agent.py                          # 交互式对话
    python agent.py --once "阿森纳 vs 利物浦 预测"
    python agent.py --serve                  # 启动 API 服务

依赖:
    pip install anthropic requests matplotlib numpy pillow
================================================================
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from loguru import logger

# The Odds API 工具
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.odds import get_match_odds, resolve_sport_key
from tools.simulate import simulate_match
from tools.live_odds import get_live_odds
from tools.historical_odds import get_historical_odds
from tools.match_data import get_fixtures as api_get_fixtures, get_team_stats

# ============================================================
# 配置
# ============================================================
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RAPIDAPI_KEY = os.getenv("FOOTBALL_RAPIDAPI_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-fable-5")

# API-Football 联赛 ID 映射
LEAGUE_IDS = {
    "英超": 39, "西甲": 140, "德甲": 78, "意甲": 135, "法甲": 61,
    "欧冠": 2, "欧联": 3, "英冠": 40, "荷甲": 88, "葡超": 94,
    "MLS": 253, "J联赛": 98, "中超": 169, "世界杯": 1,
}

LEAGUE_NAMES = {v: k for k, v in LEAGUE_IDS.items()}


# ============================================================
# API-Football 客户端 (轻量版)
# ============================================================

class APIFootball:
    """API-Football v3 via RapidAPI —— 轻量封装"""

    BASE = "https://api-football-v1.p.rapidapi.com/v3/"
    HEADERS = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
    } if RAPIDAPI_KEY else {}

    _last_call = 0.0
    RATE = 0.35

    @classmethod
    def _get(cls, endpoint: str, params: dict | None = None) -> dict:
        if not cls.HEADERS.get("x-rapidapi-key"):
            raise RuntimeError("未配置 FOOTBALL_RAPIDAPI_KEY")
        elapsed = time.time() - cls._last_call
        if elapsed < cls.RATE:
            time.sleep(cls.RATE - elapsed)
        cls._last_call = time.time()
        r = requests.get(f"{cls.BASE}{endpoint}", headers=cls.HEADERS,
                         params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ---- Fixtures ----

    @classmethod
    def get_live_fixtures(cls) -> list[dict]:
        """获取所有进行中的比赛"""
        data = cls._get("fixtures", {"live": "all"})
        return data.get("response", [])

    @classmethod
    def get_fixtures_by_date(cls, date: str, league_id: int | None = None) -> list[dict]:
        """按日期获取比赛"""
        params: dict[str, Any] = {"date": date}
        if league_id:
            params["league"] = league_id
        data = cls._get("fixtures", params)
        return data.get("response", [])

    @classmethod
    def get_fixture_detail(cls, fixture_id: int) -> dict | None:
        """获取单场比赛完整数据 (含统计)"""
        data = cls._get("fixtures", {"id": fixture_id})
        resp = data.get("response", [])
        return resp[0] if resp else None

    # ---- Teams ----

    @classmethod
    def search_team(cls, name: str) -> dict | None:
        """按名称搜索球队"""
        data = cls._get("teams", {"search": name})
        resp = data.get("response", [])
        if not resp:
            return None
        t = resp[0]["team"]
        v = resp[0].get("venue", {})
        return {"id": t["id"], "name": t["name"], "country": t.get("country", ""),
                "logo": t.get("logo"), "venue": v.get("name", ""),
                "capacity": v.get("capacity")}

    @classmethod
    def get_team_fixtures(cls, team_id: int, last: int = 5) -> list[dict]:
        """获取球队最近 N 场比赛"""
        data = cls._get("fixtures", {"team": team_id, "last": last})
        return data.get("response", [])

    @classmethod
    def get_team_statistics(cls, team_id: int, league_id: int,
                            season: int | None = None) -> dict:
        """获取球队赛季统计"""
        params = {"team": team_id, "league": league_id,
                  "season": season or datetime.now().year}
        data = cls._get("teams/statistics", params)
        return data.get("response", {})

    # ---- H2H ----

    @classmethod
    def get_h2h(cls, team_id_a: int, team_id_b: int, last: int = 20) -> list[dict]:
        """获取两队历史交锋"""
        data = cls._get("fixtures", {"h2h": f"{team_id_a}-{team_id_b}", "last": last})
        return data.get("response", [])


# ============================================================
# 工具函数实现
# ============================================================

# ---------- 工具 1: 实时比分 ----------

async def get_live_scores(league: str | None = None, team: str | None = None) -> dict[str, Any]:
    """获取实时比分和比赛状态

    调用 API-Football /fixtures?live=all 获取所有进行中的比赛，
    可按联赛或球队筛选。

    Args:
        league: 联赛名称 (如 "英超", "西甲", "欧冠")，不填返回全部
        team:   球队名称筛选，不填返回全部
    """
    try:
        fixtures = APIFootball.get_live_fixtures()
    except RuntimeError:
        return {"error": "请在 .env 中配置 FOOTBALL_RAPIDAPI_KEY", "live_matches": []}
    except Exception as e:
        return {"error": f"API 请求失败: {e}", "live_matches": []}

    if not fixtures:
        return {"live_matches": [], "message": "当前没有进行中的比赛",
                "updated_at": datetime.now().isoformat()}

    matches = []
    for f in fixtures:
        fixt = f["fixture"]
        teams = f["teams"]
        goals = f["goals"]
        league_info = f["league"]
        status = fixt.get("status", {})

        # 联赛筛选
        league_name = league_info.get("name", "")
        if league and league not in league_name:
            continue

        # 球队筛选
        home_name = teams["home"]["name"]
        away_name = teams["away"]["name"]
        if team and team not in home_name and team not in away_name:
            continue

        matches.append({
            "id": fixt["id"],
            "status": status.get("short", "?"),           # 1H/HT/2H/FT 等
            "elapsed": status.get("elapsed", 0),           # 已进行分钟
            "home_team": home_name,
            "away_team": away_name,
            "home_id": teams["home"]["id"],
            "away_id": teams["away"]["id"],
            "score": f"{goals.get('home', 0)} - {goals.get('away', 0)}",
            "home_goals": goals.get("home"),
            "away_goals": goals.get("away"),
            "competition": league_name,
            "round": league_info.get("round", ""),
            "venue": fixt.get("venue", {}).get("name", ""),
            "referee": fixt.get("referee"),
        })

    # 按进行时间排序
    matches.sort(key=lambda m: m["elapsed"], reverse=True)

    return {
        "live_matches": matches,
        "total": len(matches),
        "filter": {"league": league, "team": team},
        "updated_at": datetime.now().isoformat(),
    }


# ---------- 工具 2: 历史交锋 ----------

async def query_head_to_head(
    team_a: str,
    team_b: str,
    limit: int = 20,
) -> dict[str, Any]:
    """查询两支球队的历史交锋数据

    从 API-Football 获取真实交锋记录，包含:
    - 总交锋次数与胜平负统计
    - 最近一次交锋详情
    - 进球分布分析
    - 主客场细分

    Args:
        team_a: 球队 A 名称 (中文或英文)
        team_b: 球队 B 名称 (中文或英文)
        limit:  最多返回多少场交锋 (默认 20)
    """
    # 1. 搜索球队 ID
    try:
        info_a = APIFootball.search_team(team_a)
        info_b = APIFootball.search_team(team_b)
    except RuntimeError:
        return _mock_h2h(team_a, team_b)
    except Exception as e:
        return {"error": f"搜索球队失败: {e}"}

    if not info_a:
        return {"error": f"未找到球队: {team_a}"}
    if not info_b:
        return {"error": f"未找到球队: {team_b}"}

    # 2. 获取交锋数据
    try:
        fixtures = APIFootball.get_h2h(info_a["id"], info_b["id"], last=limit)
    except Exception as e:
        return {"error": f"获取交锋数据失败: {e}", "team_a": info_a, "team_b": info_b}

    if not fixtures:
        return {
            "team_a": info_a,
            "team_b": info_b,
            "total_matches": 0,
            "message": f"{info_a['name']} 与 {info_b['name']} 暂无交锋记录",
        }

    # 3. 统计分析
    a_wins = a_losses = draws = 0
    a_goals = b_goals = 0
    records: list[dict] = []
    home_wins = away_wins = home_losses = away_losses = 0

    for f in fixtures:
        teams = f["teams"]
        goals = f["goals"]
        g_home = goals.get("home") or 0
        g_away = goals.get("away") or 0
        home_id = teams["home"]["id"]
        away_id = teams["away"]["id"]
        a_is_home = (home_id == info_a["id"])
        a_g = g_home if a_is_home else g_away
        b_g = g_away if a_is_home else g_home

        if a_g > b_g:
            a_wins += 1
            if a_is_home:
                home_wins += 1
            else:
                away_wins += 1
        elif b_g > a_g:
            a_losses += 1
            if a_is_home:
                home_losses += 1
            else:
                away_losses += 1
        else:
            draws += 1

        a_goals += a_g
        b_goals += b_g

        records.append({
            "date": f["fixture"]["date"][:10],
            "home": teams["home"]["name"],
            "away": teams["away"]["name"],
            "score": f"{g_home}-{g_away}",
            "winner": ("A" if a_g > b_g else "B" if b_g > a_g else "DRAW"),
            "competition": f.get("league", {}).get("name", ""),
        })

    total = len(fixtures)
    a_id = info_a["id"]

    return {
        "team_a": {"name": info_a["name"], "id": info_a["id"], "logo": info_a.get("logo")},
        "team_b": {"name": info_b["name"], "id": info_b["id"], "logo": info_b.get("logo")},
        "statistics": {
            "total": total,
            f"{info_a['name']}_wins": a_wins,
            f"{info_a['name']}_losses": a_losses,
            "draws": draws,
            f"{info_a['name']}_win_rate": f"{a_wins / total * 100:.1f}%",
            "home_wins": home_wins,
            "away_wins": away_wins,
            "home_losses": home_losses,
            "away_losses": away_losses,
            f"{info_a['name']}_goals": a_goals,
            f"{info_b['name']}_goals": b_goals,
            "avg_goals_per_match": round((a_goals + b_goals) / total, 2),
        },
        "recent_matches": records[:10],
        "summary": (
            f"{info_a['name']} 近 {total} 次对阵 {info_b['name']}: "
            f"{a_wins} 胜 {draws} 平 {a_losses} 负, "
            f"胜率 {a_wins / total * 100:.1f}%, "
            f"场均进球 {a_goals / total:.1f}"
        ),
    }


def _mock_h2h(team_a: str, team_b: str) -> dict:
    """无 API Key 时的模拟交锋数据"""
    from hashlib import md5

    # 基于球队名生成确定性随机种子
    seed = int(md5(f"{team_a}{team_b}".encode()).hexdigest()[:8], 16)
    rng = __import__("random").Random(seed)

    total = rng.randint(8, 25)
    a_w = rng.randint(3, total - 3)
    b_w = rng.randint(2, total - a_w - 1)
    d = total - a_w - b_w
    a_g = a_w * 2 + rng.randint(0, a_w)
    b_g = b_w * 2 + rng.randint(0, b_w)

    return {
        "team_a": {"name": team_a, "id": None, "logo": None},
        "team_b": {"name": team_b, "id": None, "logo": None},
        "statistics": {
            "total": total,
            f"{team_a}_wins": a_w,
            f"{team_a}_losses": b_w,
            "draws": d,
            f"{team_a}_win_rate": f"{a_w / total * 100:.1f}%",
            f"{team_a}_goals": a_g,
            f"{team_b}_goals": b_g,
            "avg_goals_per_match": round((a_g + b_g) / total, 2),
        },
        "summary": (
            f"{team_a} 近 {total} 次对阵 {team_b}: "
            f"{a_w} 胜 {d} 平 {b_w} 负 (模拟数据)"
        ),
        "note": "⚠️ 模拟数据 —— 配置 FOOTBALL_RAPIDAPI_KEY 可获取真实数据",
    }


# ---------- 工具 3: 近 N 场场均 xG ----------

async def calculate_recent_xg(
    team_name: str,
    matches: int = 5,
    league: str = "英超",
) -> dict[str, Any]:
    """计算球队近 N 场比赛的场均 xG (预期进球)

    xG 计算方法:
    - 优先使用 API-Football 自带的 xG 数据 (如有)
    - 否则基于射门统计计算代理 xG:
      xG_proxy = (射正数 × 0.28) + (射偏数 × 0.04) + (关键传球 × 0.08)
    - 同时计算 xGA (预期失球)

    Args:
        team_name: 球队名称
        matches:   统计最近几场 (默认 5)
        league:    联赛名称 (用于查找正确的 league_id)
    """
    # 1. 查找球队
    try:
        info = APIFootball.search_team(team_name)
    except RuntimeError:
        return _mock_xg(team_name, matches)
    except Exception as e:
        return {"error": f"搜索球队失败: {e}"}

    if not info:
        return {"error": f"未找到球队: {team_name}"}

    # 2. 获取最近比赛
    try:
        fixtures = APIFootball.get_team_fixtures(info["id"], last=matches)
    except Exception as e:
        return {"error": f"获取比赛数据失败: {e}"}

    if not fixtures:
        return {"error": f"未找到 {team_name} 近期的比赛数据"}

    # 3. 逐场计算 xG
    match_xg_list: list[dict] = []
    total_xg = 0.0
    total_xga = 0.0
    total_goals = 0
    total_goals_conceded = 0
    valid_count = 0

    for f in fixtures:
        fixt = f["fixture"]
        teams = f["teams"]
        goals = f["goals"]
        stats_list = f.get("statistics", [])

        is_home = (teams["home"]["id"] == info["id"])
        opp_name = teams["away"]["name"] if is_home else teams["home"]["name"]
        gf = (goals.get("home") or 0) if is_home else (goals.get("away") or 0)
        ga = (goals.get("away") or 0) if is_home else (goals.get("home") or 0)
        total_goals += gf
        total_goals_conceded += ga

        # 解析该队在本场的技术统计
        team_stats = _extract_team_stats(stats_list, info["id"])

        # 计算 xG
        xg, xga, xg_method = _compute_xg(team_stats, is_home)

        match_xg_list.append({
            "date": fixt["date"][:10],
            "opponent": opp_name,
            "venue": "主场" if is_home else "客场",
            "result": f"{gf}-{ga}",
            "goals_for": gf,
            "goals_against": ga,
            "xg": round(xg, 3),
            "xga": round(xga, 3),
            "xg_diff": round(xg - xga, 3),
            "xg_method": xg_method,
            "shots": team_stats.get("total_shots"),
            "shots_on_target": team_stats.get("shots_on_target"),
            "possession": team_stats.get("possession"),
        })
        total_xg += xg
        total_xga += xga
        valid_count += 1

    if valid_count == 0:
        return {"error": "未能解析任何比赛的 xG 数据",
                "team": info["name"], "matches_retrieved": len(fixtures)}

    avg_xg = total_xg / valid_count
    avg_xga = total_xga / valid_count
    avg_goals = total_goals / valid_count

    # 判断 xG 表现
    if avg_goals > avg_xg + 0.3:
        finishing = "高效 (实际进球高于预期, 射门转化能力强)"
    elif avg_goals < avg_xg - 0.3:
        finishing = "低效 (实际进球低于预期, 可能存在终结问题)"
    else:
        finishing = "正常 (实际进球与预期基本吻合)"

    return {
        "team": info["name"],
        "team_id": info["id"],
        "period": f"近 {valid_count} 场",
        "average_xg": round(avg_xg, 3),
        "average_xga": round(avg_xga, 3),
        "average_xg_diff": round(avg_xg - avg_xga, 3),
        "average_goals": round(avg_goals, 2),
        "average_goals_conceded": round(total_goals_conceded / valid_count, 2),
        "finishing_assessment": finishing,
        "xG_trend": "上升" if len(match_xg_list) >= 3 and (
            sum(m["xg"] for m in match_xg_list[-3:]) / 3 > avg_xg
        ) else "平稳或下降",
        "match_details": match_xg_list,
        "method_note": "xG 基于射正/射偏/关键传球等统计估算，非官方 xG 数据",
    }


def _extract_team_stats(stats_list: list, team_id: int) -> dict[str, float]:
    """从 API-Football statistics 数组提取指定球队的数据"""
    result: dict[str, float] = {}
    for team_stats in stats_list:
        if team_stats.get("team", {}).get("id") != team_id:
            continue
        for stat in team_stats.get("statistics", []):
            key = stat.get("type", "").lower().replace(" ", "_")
            val = stat.get("value")
            if val is not None:
                # 百分比字符串转数字
                if isinstance(val, str) and val.endswith("%"):
                    try:
                        val = float(val.replace("%", "")) / 100
                    except ValueError:
                        val = 0.0
                try:
                    result[key] = float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    result[key] = 0.0
        break
    return result


def _compute_xg(stats: dict[str, float], is_home: bool) -> tuple[float, float, str]:
    """根据技术统计计算代理 xG

    使用加权公式:
    xG ≈ shots_on_target × 0.28 + shots_off_target × 0.04
          + (corners × 0.02) + (dangerous_attacks / total_attacks × 0.05)
    """
    sot = stats.get("shots_on_target", 0)
    total_shots = stats.get("total_shots", 0)
    shots_off = max(0, total_shots - sot)
    corners = stats.get("corner_kicks", 0)
    possession = stats.get("ball_possession", 0.5)
    dangerous = stats.get("dangerous_attacks", 0)
    total_attacks = stats.get("total_attacks", 1)

    # 如果完全没有射门数据，用伪数据
    if total_shots == 0 and sot == 0:
        # 基于控球率粗略估算
        xg = 0.5 + possession * 0.8
        xga = 0.5 + (1 - possession) * 0.8
        return xg, xga, "估算(控球率)"

    # 代理 xG
    xg = (
        sot * 0.28
        + shots_off * 0.04
        + corners * 0.02
        + (dangerous / max(total_attacks, 1)) * 0.5
    )

    # 主客场调整
    if is_home:
        xg *= 1.08  # 主场 +8%
    else:
        xg *= 0.92  # 客场 -8%

    xga = xg * (0.7 + 0.3 * (1 - possession))  # 根据控球推算对方 xG

    return max(xg, 0.1), max(xga, 0.1), "代理xG(射门统计)"


def _mock_xg(team_name: str, matches: int = 5) -> dict:
    """无 API Key 时的模拟 xG 数据"""
    from hashlib import md5
    seed = int(md5(team_name.encode()).hexdigest()[:8], 16)
    rng = __import__("random").Random(seed)

    base_xg = 1.0 + rng.random() * 1.5  # 1.0 ~ 2.5
    match_data = []
    for i in range(matches):
        xg = round(base_xg + rng.uniform(-0.5, 0.5), 3)
        xga = round(rng.uniform(0.4, 1.8), 3)
        match_data.append({
            "date": (datetime.now() - timedelta(days=(matches - i) * 7)).strftime("%Y-%m-%d"),
            "opponent": f"对手{i + 1}",
            "venue": "主场" if rng.random() > 0.5 else "客场",
            "result": f"{int(xg)}-{int(xga)}",
            "goals_for": int(xg),
            "goals_against": int(xga),
            "xg": xg,
            "xga": xga,
            "xg_diff": round(xg - xga, 3),
            "xg_method": "模拟",
            "shots": int(base_xg * 8 + rng.randint(-3, 3)),
            "shots_on_target": int(base_xg * 3 + rng.randint(-1, 2)),
        })

    avg = sum(m["xg"] for m in match_data) / len(match_data)
    return {
        "team": team_name,
        "team_id": None,
        "period": f"近 {len(match_data)} 场",
        "average_xg": round(avg, 3),
        "average_xga": round(sum(m["xga"] for m in match_data) / len(match_data), 3),
        "average_xg_diff": round(avg - sum(m["xga"] for m in match_data) / len(match_data), 3),
        "match_details": match_data,
        "method_note": "⚠️ 模拟数据 —— 配置 FOOTBALL_RAPIDAPI_KEY 获取真实 xG",
    }


# ---------- 工具 4: 球队雷达图 ----------

async def generate_radar_chart(
    team_name: str,
    compare_with: str | None = None,
    league: str = "英超",
    output_format: str = "base64",
) -> dict[str, Any]:
    """生成球队能力雷达图

    从 API-Football 获取真实球队统计数据，生成多维度雷达图:
    - 进攻 (场均进球 + 射门)
    - 防守 (零封率 + 抢断)
    - 控球 (传球成功率 + 控球率)
    - 纪律 (黄牌/犯规)
    - 效率 (射门转化率)
    - 状态 (近期胜率)

    支持单队展示和两队对比。

    Args:
        team_name:    球队名称
        compare_with: 对比球队名称 (可选)
        league:       联赛名称
        output_format: "base64" (返回图片) 或 "dict" (仅返回数据)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return {"error": "请安装 matplotlib: pip install matplotlib"}

    # 1. 获取球队数据
    team_data = await _build_radar_data(team_name, league)

    # 2. 获取对比球队数据
    compare_data = None
    if compare_with:
        compare_data = await _build_radar_data(compare_with, league)

    if output_format == "dict":
        result: dict[str, Any] = {"team": team_data}
        if compare_data:
            result["compare"] = compare_data
        return result

    # 3. 绘制雷达图
    categories = ["进攻火力", "防守稳固", "控球组织", "纪律性", "终结效率", "近期状态"]
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    # 主队
    values = [
        team_data["attack"],
        team_data["defense"],
        team_data["possession"],
        team_data["discipline"],
        team_data["efficiency"],
        team_data["form"],
    ]
    values += values[:1]
    ax.fill(angles, values, alpha=0.25, color="#38bdf8")
    ax.plot(angles, values, "o-", linewidth=2, color="#38bdf8",
            label=team_data["name"], markersize=6)

    # 对比队
    if compare_data:
        cmp_values = [
            compare_data["attack"],
            compare_data["defense"],
            compare_data["possession"],
            compare_data["discipline"],
            compare_data["efficiency"],
            compare_data["form"],
        ]
        cmp_values += cmp_values[:1]
        ax.fill(angles, cmp_values, alpha=0.20, color="#f472b6")
        ax.plot(angles, cmp_values, "s--", linewidth=2, color="#f472b6",
                label=compare_data["name"], markersize=6)

    # 样式
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color="white", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], color="#94a3b8", fontsize=8)
    ax.set_rlabel_position(0)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")
    ax.grid(color="#334155", linewidth=0.5)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1),
              facecolor="#1e293b", edgecolor="#334155", labelcolor="white")

    title = f"⚽ {team_data['name']}"
    if compare_data:
        title += f"  vs  {compare_data['name']}"
    ax.set_title(title, color="white", fontsize=14, fontweight="bold", pad=20)

    # 导出
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=120, facecolor="#0f172a", bbox_inches="tight")
    plt.close()
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode()

    return {
        "team": team_data,
        "compare": compare_data,
        "chart_base64": img_base64,
        "chart_mime": "image/png",
        "dimensions": categories,
        "note": "评分基于赛季统计数据归一化计算，范围 0-100",
    }


async def _build_radar_data(team_name: str, league: str) -> dict[str, Any]:
    """构建雷达图所需的能力维度数据"""
    # 尝试从 API 获取真实数据
    stats = None
    info = None
    if RAPIDAPI_KEY:
        try:
            info = APIFootball.search_team(team_name)
        except Exception:
            info = None
        if info:
            league_id = LEAGUE_IDS.get(league, 39)
            try:
                stats = APIFootball.get_team_statistics(info["id"], league_id)
            except Exception:
                stats = None

    # 提取指标
    if stats and stats.get("fixtures"):
        f = stats.get("fixtures", {})
        g = stats.get("goals", {})
        played = f.get("played", {}).get("total", 1) or 1
        wins = f.get("wins", {}).get("total", 0) or 0
        draws = f.get("draws", {}).get("total", 0) or 0

        gf = float(g.get("for", {}).get("average", {}).get("total", 1.4) or 1.4)
        ga = float(g.get("against", {}).get("average", {}).get("total", 1.2) or 1.2)
        win_rate = (wins + draws * 0.5) / played * 100

        # 归一化到 0-100
        attack = min(100, gf / 3.0 * 100)
        defense = min(100, (2.5 - ga) / 2.5 * 100)
        possession = 55  # 默认值，API 可能不返回
        discipline = 50
        efficiency = min(100, (gf / max((gf + 0.3), 0.1)) * 60)
        form = win_rate
    else:
        # ELO 推算
        from src.models.elo import EloSystem
        elo = EloSystem.get_elo(team_name)
        strength = (elo - 1500) / 400

        attack = min(100, 45 + strength * 35)
        defense = min(100, 45 + strength * 30)
        possession = min(100, 48 + strength * 25)
        discipline = min(100, 50 - strength * 15)
        efficiency = min(100, 50 + strength * 20)
        form = min(100, 50 + strength * 25)
        info = {"name": team_name, "id": None, "logo": None}

    return {
        "name": info["name"] if info else team_name,
        "team_id": info.get("id") if info else None,
        "attack": round(attack, 1),
        "defense": round(defense, 1),
        "possession": round(possession, 1),
        "discipline": round(discipline, 1),
        "efficiency": round(efficiency, 1),
        "form": round(form, 1),
        "data_source": "API-Football" if stats else "ELO估算",
    }


# ============================================================
# Anthropic Tool Schemas
# ============================================================

TOOLS = [
    {
        "name": "get_live_scores",
        "description": "获取当前所有进行中的足球比赛实时比分。可按联赛或球队筛选。返回比分、比赛时间、状态等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "league": {
                    "type": "string",
                    "description": "联赛筛选: 英超/西甲/德甲/意甲/法甲/欧冠 等 (不填返回全部)",
                },
                "team": {
                    "type": "string",
                    "description": "球队名称筛选 (不填返回全部)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_head_to_head",
        "description": "查询两支球队的历史交锋记录。返回总交锋场次、胜平负统计、进球分析、近期交锋详情。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_a": {
                    "type": "string",
                    "description": "球队 A 名称 (中文或英文, 如 'Arsenal' 或 '阿森纳')",
                },
                "team_b": {
                    "type": "string",
                    "description": "球队 B 名称",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回最近多少场交锋 (默认 20)",
                },
            },
            "required": ["team_a", "team_b"],
        },
    },
    {
        "name": "calculate_recent_xg",
        "description": """计算球队近N场比赛的场均xG(预期进球)和xGA(预期失球)。
基于射正数、射偏数、角球等技术统计估算。
返回逐场xG明细、平均值、趋势判断、终结效率评估。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "球队名称",
                },
                "matches": {
                    "type": "integer",
                    "description": "统计最近几场 (默认 5)",
                },
                "league": {
                    "type": "string",
                    "description": "联赛名称 (默认 '英超')",
                },
            },
            "required": ["team_name"],
        },
    },
    {
        "name": "generate_radar_chart",
        "description": """生成球队能力六维雷达图。维度包括:
1. 进攻火力 (场均进球+射门)
2. 防守稳固 (零封率+抢断)
3. 控球组织 (传球成功率+控球率)
4. 纪律性   (黄牌/犯规)
5. 终结效率 (射门转化率)
6. 近期状态 (近5场胜率)
支持单队展示和两队对比。返回 base64 编码的 PNG 图片。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "球队名称",
                },
                "compare_with": {
                    "type": "string",
                    "description": "对比球队名称 (可选, 用于两队对比)",
                },
                "league": {
                    "type": "string",
                    "description": "联赛名称 (默认 '英超')",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["base64", "dict"],
                    "description": "输出格式: base64=返回图片, dict=仅返回数据",
                },
            },
            "required": ["team_name"],
        },
    },
    {
        "name": "get_match_odds",
        "description": """获取指定联赛所有即将进行比赛的实时赔率数据。

数据源: The Odds API (覆盖 Bet365/Pinnacle/William Hill/Betfair 等 40+ 博彩公司)

返回内容:
- 每场比赛的胜平负赔率 (h2h)、让球盘 (spreads)、大小球 (totals)
- 多家博彩公司赔率对比
- Pinnacle (最精准) 的赔率作为市场基准
- 赔率离散度分析 (检测异常定价)
- 平均市场抽水率 (margin)

用途:
- 判断市场对某场比赛的集体预期
- 对比模型预测概率 vs 市场隐含概率
- 检测赔率骤降 (steam move) → 大资金涌入信号
- 计算价值投注机会 (模型概率 > 市场隐含概率)

联赛代码:
  欧冠=soccer_uefa_champions_league, 英超=soccer_epl,
  西甲=soccer_spain_la_liga, 德甲=soccer_germany_bundesliga,
  意甲=soccer_italy_serie_a, 法甲=soccer_france_ligue_one,
  MLS=soccer_usa_mls, 欧联=soccer_uefa_europa_league""",
        "input_schema": {
            "type": "object",
            "properties": {
                "sport_key": {
                    "type": "string",
                    "description": "联赛标识, 如 soccer_uefa_champions_league (欧冠) 或 soccer_epl (英超)。支持中文输入自动转换。不填=全部赛事。",
                },
                "regions": {
                    "type": "string",
                    "description": "博彩公司地区: uk,eu,us,au (默认 uk,eu,us)",
                },
                "markets": {
                    "type": "string",
                    "description": "玩法: h2h(胜平负),spreads(让球),totals(大小球) (默认 h2h,spreads,totals)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "simulate_match",
        "description": """蒙特卡洛泊松模拟器 —— 10000次采样生成完整比分分布。

输入球队攻防力参数，输出:
- 胜平负概率分布
- 最可能比分 Top10 (精确到比分)
- 大小球概率 (O1.5 / O2.5 / O3.5 / O4.5)
- 双方进球 (BTTS) 概率
- 半场/下半场进球分布
- 预期进球 95% 置信区间
- 精确比分查询 (如 "2-1" 的精确概率)

攻防力参数可从 get_team_statistics 获取，或用 elo_to_strength() 从 ELO 估算。
典型调用: simulate_match(home_attack=1.15, home_defense=0.92, away_attack=1.05, away_defense=1.10)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "home_team": {"type": "string", "description": "主队名称"},
                "away_team": {"type": "string", "description": "客队名称"},
                "home_attack": {"type": "number", "description": "主队进攻力 (>1=强, 默认1.0)"},
                "home_defense": {"type": "number", "description": "主队防守力 (>1=差, <1=好, 默认1.0)"},
                "away_attack": {"type": "number", "description": "客队进攻力"},
                "away_defense": {"type": "number", "description": "客队防守力"},
                "home_advantage": {"type": "number", "description": "主场优势加成 (通常0.2-0.4, 默认0.3)"},
                "league_avg_goals": {"type": "number", "description": "联赛场均总进球 (英超≈2.75, 默认2.70)"},
                "n_sims": {"type": "integer", "description": "模拟次数 (默认10000, 越大越精确)"},
            },
            "required": [],
        },
    },
]

# 工具路由
HANDLERS = {
    "get_live_scores":        get_live_scores,
    "query_head_to_head":     query_head_to_head,
    "calculate_recent_xg":    calculate_recent_xg,
    "generate_radar_chart":   generate_radar_chart,
    "get_match_odds":         get_match_odds,
    "simulate_match":         simulate_match,
    "get_live_odds":          get_live_odds,
    "get_historical_odds":    get_historical_odds,
    "get_fixtures":           api_get_fixtures,
    "get_team_stats":         get_team_stats,
}


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """你是一名资深足球数据分析师 AI，遵循以下分析框架。

## 可用工具

| 工具 | 用途 |
|------|------|
| `get_live_odds` | 获取当天实时赔率 (The Odds API, 初盘+即时盘对比, 3分钟缓存) |
| `get_match_odds` | 获取实时赔率 (40+博彩公司, Pinnacle基准) |
| `get_historical_odds` | 查询近5赛季历史终盘赔率 (football-data.co.uk CSV) |
| `get_fixtures` | 获取赛程+实时比分 (API-Football v3) |
| `get_team_stats` | 获取球队近期战绩+状态 (API-Football) |
| `get_live_scores` | 查看正在进行的比赛实时比分 |
| `simulate_match` | 蒙特卡洛泊松模拟 (10000次采样→比分分布) |
| `calculate_recent_xg` | 计算球队近5场场均xG和xGA |
| `query_head_to_head` | 查询两队历史交锋数据 |
| `generate_radar_chart` | 生成球队六维能力雷达图 |

---

## 一、数据优先级 (严格遵守)

分析任何比赛时，按以下优先级使用数据:

### 第1层: 市场基准 (最优先)
1. 从 `get_live_odds` 获取当天实时赔率，对比初盘和即时盘的差异
2. 从 `get_historical_odds` 查询同类比赛近5赛季终盘赔率，判断盘口深度
3. 从 `get_match_odds` 获取 Pinnacle/Bet365 多公司对比赔率
4. 用 **Shin 方法** (非简单 1/odds) 剥离 margin，得到"去水概率"
5. 将去水概率作为**市场基准预测**

### 第2层: 球队真实状态
1. 用 `get_team_stats` 获取球队近期战绩(W/D/L)和进失球数据
2. 用 `get_fixtures` 获取赛程和实时比分
3. 用 `calculate_recent_xg` 获取近5场 xG 差值 (xG - xGA)
4. **xG 差值 > +0.5** → 球队状态显著优于实际战绩
5. 核心判断: xG方向与赔率方向一致 → 信心增强; 背离 → 价值机会

### 第3层: 蒙特卡洛验证
1. 调用 `simulate_match` 输入攻防力参数
2. 对比蒙特卡洛输出的比分分布 vs 市场赔率隐含的比分分布
3. 蒙特卡洛概率 > 市场隐含概率 +5% → 潜在价值

### 第4层: 背景信息
- 交锋历史、伤停、联赛排名作为辅助解释

---

## 二、赔率分析方法

### Shin 去水 (必须使用)
赔率不能直接 1/odds 当概率 (有抽水)。
Shin 模型基于部分信息假设，能更准确分离真实概率与 margin。

### 市场热度五维度
1. **方向**: Pinnacle 最低赔率方向 = 专业资金流向
2. **离散度**: >8% = 市场分歧大 = 冷门风险; <3% = 共识强
3. **水位变化**: 骤降 >10% = "蒸汽移动" → 内幕信息信号
4. **价值**: 模型概率 - 市场隐含概率 >5% = 价值投注
5. **抽水率**: <3% 可信; >7% 打折

---

## 三、xG 分析规则

xG 是近十年足球分析最大的革命。用 xG 代替真实比分评估球队实力:
- **长期预测能力远强于实际结果** (过滤了运气成分)
- 公式化规则: xG 差值为正且 >0.5 的球队，具有"数据支撑"的额外价值
- 如果一支球队 xG 很高但近期战绩差 → 被市场低估 → 价值机会

---

## 四、贝叶斯动态更新 (比赛进行中)

如果用户询问正在进行的比赛:
1. 获取当前比分和剩余时间
2. 使用贝叶斯公式更新赛前概率:
   P(终场胜 | 当前比分, 剩余分钟) ∝ P(当前比分 | 终场胜) × P(赛前胜)
3. 输出动态胜率走势

---

## 五、蒙特卡洛模拟 (simulate_match)

当需要生成比分预测时:
1. 输入主客队进攻/防守强度、主场优势因子
2. 泊松采样 10000 次
3. 输出: 胜平负概率分布、最可能比分 Top10、大小球、双方进球、半场分布、置信区间

---

## 输出规则
- 用中文回复，数据驱动，避免主观
- **先看赔率隐含概率 (Shin 去水后)，再对比 xG 差值**
- xG 与赔率一致 → 报告信心度
- xG 与赔率背离 → 标注"价值机会"并解释原因
- 提醒: "足球比赛存在不确定性，分析仅供参考"
"""


# ============================================================
# Agent 主循环
# ============================================================

class FootyAgent:
    """足球分析智能体 —— 主循环"""

    def __init__(self, api_key: str = "", model: str = "") -> None:
        # 延迟导入 anthropic (允许不安装也能查看帮助)
        import anthropic
        self.client = anthropic.Anthropic(
            api_key=api_key or ANTHROPIC_API_KEY
        )
        self.model = model or ANTHROPIC_MODEL
        self.max_turns = 6

    async def run(self, user_input: str) -> str:
        """执行一轮对话，返回 AI 最终分析结果"""

        messages: list[dict] = [
            {"role": "user", "content": user_input}
        ]

        for turn in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # 分离 text 和 tool_use
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_blocks:
                return "\n".join(b.text for b in text_blocks)

            # 记录本轮工具调用
            names = [b.name for b in tool_blocks]
            print(f"  [{turn + 1}] 🔧 {', '.join(names)}")

            # 添加 assistant 消息
            messages.append({
                "role": "assistant",
                "content": [b.to_dict() for b in response.content],
            })

            # 并发执行所有工具 (同一轮多个 tool_use)
            tool_results = await asyncio.gather(*[
                self._dispatch(b) for b in tool_blocks
            ])

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],
                        "content": json.dumps(r["result"], ensure_ascii=False, indent=2),
                    }
                    for r in tool_results
                ],
            })

        # 超时兜底
        final = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages + [{
                "role": "user",
                "content": "请基于以上所有数据，用中文给出综合结论。",
            }],
        )
        return final.content[0].text

    async def _dispatch(self, block) -> dict:
        """执行单个工具调用"""
        name = block.name
        args = block.input or {}
        handler = HANDLERS.get(name)
        if handler is None:
            result = {"error": f"未知工具: {name}"}
        else:
            try:
                result = await handler(**args)
            except Exception as e:
                result = {"error": str(e)}
        return {"id": block.id, "name": name, "result": result}


# ============================================================
# CLI 入口
# ============================================================

def check_deps() -> list[str]:
    """检查缺少的依赖"""
    missing = []
    for mod in ["anthropic", "requests", "dotenv"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    # matplotlib 是可选依赖
    try:
        import matplotlib
    except ImportError:
        missing.append("matplotlib (雷达图功能需要)")
    return missing


async def interactive():
    """交互式对话模式"""
    missing = check_deps()
    if missing:
        print(f"缺少依赖: {', '.join(missing)}")

    if not ANTHROPIC_API_KEY:
        print("❌ 请在 .env 中设置 ANTHROPIC_API_KEY")
        sys.exit(1)

    agent = FootyAgent()

    print("""
╔══════════════════════════════════════════════════╗
║            ⚽  足球分析智能体                      ║
║  实时比分 · 交锋查询 · xG分析 · 雷达图            ║
║                                                  ║
║  数据源:""", end="")
    if RAPIDAPI_KEY:
        print("  API-Football (RapidAPI)                ║")
    else:
        print("  模拟数据 (配置 RAPIDAPI_KEY 获取真实数据) ║")
    print("""║  输入 'quit' 退出, 'clear' 清屏              ║
╚══════════════════════════════════════════════════╝
""")

    while True:
        try:
            user_input = input("\n🧑 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见!")
            break
        if user_input.lower() == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        print("⏳", end="", flush=True)
        try:
            result = await agent.run(user_input)
            print(f"\r🤖 AI:\n{result}")
        except Exception as e:
            print(f"\r❌ 错误: {e}")


def once(query: str):
    """单次查询模式 (标准 Tool Use)"""
    async def _run():
        agent = FootyAgent()
        result = await agent.run(query)
        print(result)
    asyncio.run(_run())


def plan_once(query: str):
    """单次查询模式 (Plan-and-Execute)"""
    async def _run():
        from src.agent.plan_execute_agent import PlanExecuteAgent
        agent = PlanExecuteAgent()
        result = await agent.run(query)
        print(result)
    asyncio.run(_run())


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("""
模式:
  python agent.py                       交互对话 (标准 Tool Use)
  python agent.py --plan                交互对话 (Plan-and-Execute)
  python agent.py --once "问题"         单次查询 (标准 Tool Use)
  python agent.py --plan --once "问题"  单次查询 (Plan-and-Execute)
  python agent.py --serve               Web 服务
        """)
        return

    if "--serve" in sys.argv:
        from src.web.app import app
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
        return

    # Plan-and-Execute 模式
    use_plan = "--plan" in sys.argv

    if "--once" in sys.argv:
        idx = sys.argv.index("--once")
        if idx + 1 < len(sys.argv):
            query = sys.argv[idx + 1]
            if use_plan:
                plan_once(query)
            else:
                once(query)
        else:
            print("用法: python agent.py --plan --once '你的问题'")
        return

    if use_plan:
        asyncio.run(interactive_plan())
    else:
        asyncio.run(interactive())


async def interactive_plan():
    """Plan-and-Execute 交互模式"""
    from src.agent.plan_execute_agent import PlanExecuteAgent

    if not ANTHROPIC_API_KEY:
        print("❌ 请在 .env 中设置 ANTHROPIC_API_KEY")
        sys.exit(1)

    agent = PlanExecuteAgent()

    print("""
╔══════════════════════════════════════════════════╗
║     ⚽  足球分析智能体  [Plan & Execute 模式]      ║
║  🧠 理解意图 → 📋 制定计划 → ⚡ 执行 → ✅ 校验    ║
║                                                  ║
║  数据源:""", end="")
    if RAPIDAPI_KEY:
        print("  API-Football (RapidAPI)                ║")
    else:
        print("  模拟数据 (配置 RAPIDAPI_KEY 获取真实数据) ║")
    print("""║  输入 'quit' 退出                        ║
╚══════════════════════════════════════════════════╝
""")

    while True:
        try:
            user_input = input("\n🧑 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见!")
            break
        if user_input.lower() == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        try:
            result = await agent.run(user_input)
            print(f"\n{result}")
        except Exception as e:
            logger.error(f"Agent 错误: {e}")
            print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    main()
