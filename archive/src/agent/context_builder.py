"""
动态上下文构建器

每次分析前，实时拉取相关数据并格式化为结构化 JSON，
注入到 Prompt 的 <current_data> 区段。

数据维度:
- 两队近期战绩 (近5场)
- 伤停信息
- 联赛排名
- 交锋历史
- 天气 (如有)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from loguru import logger

from src.data.api_client import create_api_client
from src.models.elo import EloSystem

api = create_api_client()


async def build_match_context(
    home_team: str,
    away_team: str,
    competition: str = "英超",
) -> str:
    """构建比赛分析动态上下文

    Returns:
        格式化的 <current_data> XML 字符串，直接嵌入 System Prompt
    """
    data: dict[str, Any] = {
        "match": {
            "home_team": home_team,
            "away_team": away_team,
            "competition": competition,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }

    # 1. ELO 评分
    elo_home = EloSystem.get_elo(home_team)
    elo_away = EloSystem.get_elo(away_team)
    elo_gap = elo_home - elo_away + EloSystem.HOME_ADVANTAGE
    data["elo"] = {
        home_team: {"rating": elo_home, "tier": _elo_tier(elo_home)},
        away_team: {"rating": elo_away, "tier": _elo_tier(elo_away)},
        "home_advantage_adjusted_gap": round(elo_gap, 1),
        "estimated_home_win_prob": _elo_to_win_prob(elo_gap),
    }

    # 2. ELO 预测
    elo_probs = EloSystem.win_probability(home_team, away_team, home_a=True)
    data["elo_prediction"] = {
        "home_win": f"{elo_probs['home_win'] * 100:.1f}%",
        "draw": f"{elo_probs['draw'] * 100:.1f}%",
        "away_win": f"{elo_probs['away_win'] * 100:.1f}%",
    }

    # 3. 球队统计 (尝试 API)
    try:
        from src.agent.tools import get_team_statistics
        home_stats = await get_team_statistics(home_team, _comp_to_code(competition))
        away_stats = await get_team_statistics(away_team, _comp_to_code(competition))

        if "stats" in home_stats:
            data["team_stats"] = {
                home_team: _extract_key_stats(home_stats),
                away_team: _extract_key_stats(away_stats),
            }
        else:
            data["team_stats"] = {
                home_team: home_stats.get("estimated", {}),
                away_team: away_stats.get("estimated", {}),
            }
            data["team_stats"]["_note"] = "基于 ELO 估算，配置 API Key 获取真实数据"
    except Exception as e:
        logger.warning(f"获取球队统计失败: {e}")
        data["team_stats"] = {
            home_team: _estimate_stats(home_team),
            away_team: _estimate_stats(away_team),
        }

    # 4. 交锋
    try:
        from src.agent.tools import analyze_head_to_head
        h2h = await analyze_head_to_head(home_team, away_team)
        data["head_to_head"] = h2h.get("summary", "暂无数据")
    except Exception as e:
        logger.warning(f"获取交锋数据失败: {e}")
        data["head_to_head"] = "暂无数据"

    # 5. 伤停占位 (需要额外 API)
    data["injuries"] = {
        "_note": "伤停数据需要额外 API (如 Sportmonks)，当前未集成",
        home_team: "暂无数据",
        away_team: "暂无数据",
    }

    # 6. 天气占位
    data["weather"] = {
        "_note": "天气数据可从 OpenWeatherMap 等 API 获取，当前未集成",
    }

    # 格式化为 XML
    return _format_context(data)


async def build_team_analysis_context(team_name: str, competition: str = "英超") -> str:
    """构建单队分析上下文"""
    data: dict[str, Any] = {
        "team": team_name,
        "competition": competition,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "elo": {
            "rating": EloSystem.get_elo(team_name),
            "tier": _elo_tier(EloSystem.get_elo(team_name)),
        },
    }

    try:
        from src.agent.tools import get_team_statistics
        stats = await get_team_statistics(team_name, _comp_to_code(competition))
        data["stats"] = stats.get("stats") or stats.get("estimated", {})
    except Exception:
        data["stats"] = _estimate_stats(team_name)

    return _format_context(data)


def _format_context(data: dict) -> str:
    """将 dict 格式化为 <current_data> XML"""
    json_str = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return f"""<current_data>
{json_str}
</current_data>"""


def _elo_tier(elo: float) -> str:
    if elo >= 1850:
        return "世界顶级"
    elif elo >= 1750:
        return "欧洲一流"
    elif elo >= 1600:
        return "欧洲二流"
    elif elo >= 1450:
        return "中游水平"
    return "下游保级"


def _elo_to_win_prob(gap: float) -> str:
    """ELO 差值转胜率估计"""
    p = 1.0 / (1.0 + 10 ** (-gap / 400.0))
    return f"{p * 100:.1f}%"


def _comp_to_code(competition: str) -> str:
    """中文联赛名 → 代码"""
    mapping = {
        "英超": "PL", "西甲": "PD", "德甲": "BL1",
        "意甲": "SA", "法甲": "FL1", "欧冠": "CL",
        "英冠": "ELC", "荷甲": "DED", "葡超": "PPL",
    }
    return mapping.get(competition, "PL")


def _extract_key_stats(result: dict) -> dict:
    """从 get_team_statistics 结果中提取关键字段"""
    stats = result.get("stats", {})
    return {
        "form": stats.get("form", ""),
        "played": stats.get("played", 0),
        "wins": stats.get("wins", 0),
        "draws": stats.get("draws", 0),
        "losses": stats.get("losses", 0),
        "goals_for_avg": stats.get("goals_for_avg", 0),
        "goals_against_avg": stats.get("goals_against_avg", 0),
        "avg_shots": stats.get("avg_shots", 0),
        "avg_shots_on_target": stats.get("avg_shots_on_target", 0),
        "clean_sheets": stats.get("clean_sheets", 0),
        "failed_to_score": stats.get("failed_to_score", 0),
        "data_source": result.get("source", "unknown"),
    }


def _estimate_stats(team_name: str) -> dict:
    elo = EloSystem.get_elo(team_name)
    s = (elo - 1500) / 400.0
    return {
        "form": "?",
        "goals_for_avg": round(1.3 + s * 0.7, 2),
        "goals_against_avg": round(1.2 - s * 0.5, 2),
        "_note": "ELO 估算",
    }
