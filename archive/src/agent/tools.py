"""
Anthropic Function Calling 工具定义

所有工具遵循 Anthropic tool_use 规范:
每个工具返回结构化数据, 供 Claude 分析和生成回复

数据源优先级: API-Football > football-data.org > 模拟数据
API-Football 提供射门/控球等丰富数据, 显著提升预测精度
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from src.data.api_client import (
    APIFootballClient,
    BaseFootballAPI,
    MockFootballAPI,
    create_api_client,
)
from src.models.elo import EloSystem
from src.models.prediction import PoissonPredictor, TeamStats

# 全局实例
api = create_api_client()
predictor = PoissonPredictor()

# 是否为真实 API (有进阶数据)
IS_REAL_API = isinstance(api, APIFootballClient)


# ============================================================
# 工具 1: 搜索比赛
# ============================================================

async def search_matches(
    competition: str = "PL",
    matchday: int | None = None,
    date: str | None = None,
    status: str = "SCHEDULED",
) -> dict:
    """搜索比赛

    Args:
        competition: 联赛代码 (PL=英超, PD=西甲, BL1=德甲, SA=意甲, FL1=法甲, CL=欧冠)
        matchday: 比赛轮次 (可选)
        date: 指定日期 YYYY-MM-DD (可选)
        status: NS=未开始, FT=已结束, LIVE=进行中
    """
    try:
        # 状态码映射
        status_map = {"SCHEDULED": "NS", "FINISHED": "FT", "LIVE": "LIVE"}
        api_status = status_map.get(status, "NS")

        result = api.get_matches(
            competition=competition,
            matchday=matchday,
            status=api_status,
            date=date,
        )
        matches = result.get("matches", [])

        if not matches:
            return {
                "matches": [],
                "message": f"该条件下未找到比赛 (联赛: {competition}, 状态: {status})",
                "source": api.NAME,
            }

        return {
            "matches": matches[:20],
            "total": len(matches),
            "source": api.NAME,
        }
    except Exception as e:
        return {"error": str(e), "matches": []}


# ============================================================
# 工具 2: 预测比赛
# ============================================================

async def predict_match(
    home_team: str,
    away_team: str,
    home_goals_scored: float | None = None,
    home_goals_conceded: float | None = None,
    away_goals_scored: float | None = None,
    away_goals_conceded: float | None = None,
    home_form: list[str] | None = None,
    away_form: list[str] | None = None,
) -> dict[str, Any]:
    """预测单场足球比赛结果

    使用泊松分布模型计算胜平负概率、预期比分、大小球等。

    Args:
        home_team: 主队名称
        away_team: 客队名称
        home_goals_scored: 主队场均进球 (可选, 默认从ELO推算)
        home_goals_conceded: 主队场均失球 (可选)
        away_goals_scored: 客队场均进球 (可选)
        away_goals_conceded: 客队场均失球 (可选)
        home_form: 主队近期战绩, 如 ['W','W','D','L','W'] (可选)
        away_form: 客队近期战绩, 如 ['L','D','W','W','L'] (可选)
    """
    # 联赛平均数据
    LEAGUE_AVG_SCORED = 1.40
    LEAGUE_AVG_CONCEDED = 1.40
    LEAGUE_HOME = 1.53
    LEAGUE_AWAY = 1.14

    # 默认值 (基于 ELO 推算)
    if home_goals_scored is None:
        elo = EloSystem.get_elo(home_team)
        home_goals_scored = 0.8 + (elo - 1500) / 400.0
        home_goals_scored = round(max(home_goals_scored, 0.6), 2)

    if home_goals_conceded is None:
        elo = EloSystem.get_elo(home_team)
        home_goals_conceded = 1.5 - (elo - 1500) / 500.0
        home_goals_conceded = round(max(home_goals_conceded, 0.5), 2)

    if away_goals_scored is None:
        elo = EloSystem.get_elo(away_team)
        away_goals_scored = 0.7 + (elo - 1500) / 450.0
        away_goals_scored = round(max(away_goals_scored, 0.5), 2)

    if away_goals_conceded is None:
        elo = EloSystem.get_elo(away_team)
        away_goals_conceded = 1.6 - (elo - 1500) / 500.0
        away_goals_conceded = round(max(away_goals_conceded, 0.6), 2)

    # 计算攻防实力
    home_attack, home_defense = predictor.estimate_strength(
        home_goals_scored, home_goals_conceded, LEAGUE_AVG_SCORED, LEAGUE_AVG_CONCEDED
    )
    away_attack, away_defense = predictor.estimate_strength(
        away_goals_scored, away_goals_conceded, LEAGUE_AVG_SCORED, LEAGUE_AVG_CONCEDED
    )

    # 近期状态加权
    home_form_points = _calc_form_points(home_form) if home_form else 0.0
    away_form_points = _calc_form_points(away_form) if away_form else 0.0

    # 状态影响 (±10%)
    form_factor_home = 1.0 + (home_form_points - 1.5) * 0.06
    form_factor_away = 1.0 + (away_form_points - 1.5) * 0.06

    home_attack *= max(form_factor_home, 0.85)
    away_attack *= max(form_factor_away, 0.85)

    # 构建球队统计
    home_stats = TeamStats(
        name=home_team,
        avg_goals_scored=home_goals_scored,
        avg_goals_conceded=home_goals_conceded,
        attack_strength=home_attack,
        defense_strength=away_defense,    # 注意: 防守实力影响对方进球
        recent_form=home_form or [],
        form_points=home_form_points,
        elo_rating=EloSystem.get_elo(home_team),
    )
    away_stats = TeamStats(
        name=away_team,
        avg_goals_scored=away_goals_scored,
        avg_goals_conceded=away_goals_conceded,
        attack_strength=away_attack,
        defense_strength=home_defense,
        recent_form=away_form or [],
        form_points=away_form_points,
        elo_rating=EloSystem.get_elo(away_team),
    )

    # 泊松预测
    result = predictor.predict(home_stats, away_stats, LEAGUE_HOME, LEAGUE_AWAY)

    # ELO 预测 (交叉验证)
    elo_probs = EloSystem.win_probability(home_team, away_team, home_a=True)

    # 融合泊松和ELO (权重 60:40)
    fused_home = result.home_win_prob * 0.6 + elo_probs["home_win"] * 0.4
    fused_draw = result.draw_prob * 0.6 + elo_probs["draw"] * 0.4
    fused_away = result.away_win_prob * 0.6 + elo_probs["away_win"] * 0.4

    # 归一化
    total = fused_home + fused_draw + fused_away
    fused_home, fused_draw, fused_away = fused_home / total, fused_draw / total, fused_away / total

    # 格式化最可能比分
    scores = []
    for (h, a), prob in result.likely_scores:
        scores.append({
            "score": f"{h}-{a}",
            "probability": round(prob, 4),
            "pct": f"{prob * 100:.1f}%",
        })

    # 预测结论
    if fused_home >= fused_away and fused_home >= fused_draw:
        recommendation = f"主胜 ({home_team})"
    elif fused_away >= fused_home and fused_away >= fused_draw:
        recommendation = f"客胜 ({away_team})"
    else:
        recommendation = "平局"

    return {
        "home_team": home_team,
        "away_team": away_team,
        # 融合概率
        "prediction": {
            "home_win": round(fused_home * 100, 1),
            "draw": round(fused_draw * 100, 1),
            "away_win": round(fused_away * 100, 1),
            "recommendation": recommendation,
        },
        # 详细数据
        "expected_goals": {
            "home": result.home_expected_goals,
            "away": result.away_expected_goals,
        },
        "likely_scores": scores,
        "betting_markets": {
            "over_2_5_goals": f"{result.over_25_prob * 100:.1f}%",
            "over_3_5_goals": f"{result.over_35_prob * 100:.1f}%",
            "both_to_score": f"{result.both_to_score_prob * 100:.1f}%",
        },
        "team_stats": {
            "home": {
                "elo": EloSystem.get_elo(home_team),
                "attack_strength": home_attack,
                "defense_strength": home_defense,
                "form_points": home_form_points,
            },
            "away": {
                "elo": EloSystem.get_elo(away_team),
                "attack_strength": away_attack,
                "defense_strength": away_defense,
                "form_points": away_form_points,
            },
        },
    }


# ============================================================
# 工具 2.5: 球队赛季统计 (API-Football 独有增强)
# ============================================================

async def get_team_statistics(
    team_name: str,
    competition: str = "PL",
    season: int | None = None,
) -> dict[str, Any]:
    """获取球队本赛季详细统计数据

    包括: 场均进球/失球、射门数、控球率、零封率等
    这些数据直接来自 API-Football, 用于增强预测精度。

    Args:
        team_name: 球队名称
        competition: 联赛代码
        season: 赛季年份 (默认当前)
    """
    if season is None:
        season = datetime.now().year

    # 查找球队 ID
    team_id = _resolve_team_id(team_name)
    if team_id is None:
        return {"error": f"未找到球队: {team_name}", "team_name": team_name}

    try:
        # API-Football 内部联赛 ID
        league_id_map = {
            "PL": 39, "PD": 140, "BL1": 78, "SA": 135, "FL1": 61,
            "CL": 2, "ELC": 40, "DED": 88, "PPL": 94,
        }
        league_id = league_id_map.get(competition.upper(), 39)

        stats = api.get_team_statistics(team_id, league_id, season)
        if not stats:
            return {
                "team_name": team_name,
                "warning": "API 未返回统计数据, 使用 ELO 估算值",
                "estimated": _estimate_team_stats(team_name),
                "source": "ELO估算",
            }

        return {
            "team_name": team_name,
            "team_id": team_id,
            "season": season,
            "league": competition,
            "stats": stats,
            "source": api.NAME,
        }
    except Exception as e:
        logger.warning(f"获取球队统计失败 ({team_name}): {e}")
        return {
            "team_name": team_name,
            "error": str(e),
            "estimated": _estimate_team_stats(team_name),
            "source": "ELO估算(降级)",
        }


def _estimate_team_stats(team_name: str) -> dict:
    """根据 ELO 估算球队统计数据 (降级方案)"""
    elo = EloSystem.get_elo(team_name)
    strength = (elo - 1500) / 400.0
    return {
        "elo_rating": elo,
        "goals_for_avg": round(1.3 + strength * 0.7, 2),
        "goals_against_avg": round(1.2 - strength * 0.5, 2),
        "avg_shots": round(10 + strength * 5, 1),
        "avg_shots_on_target": round(3.5 + strength * 2, 1),
        "avg_possession": f"{int(48 + strength * 8)}%",
        "wins": max(10, int(15 + strength * 8)),
        "draws": max(5, int(10 - strength * 2)),
        "losses": max(5, int(13 - strength * 6)),
    }


# ============================================================
# 工具 3: 联赛积分榜
# ============================================================

async def get_standings(competition: str = "PL") -> dict:
    """获取联赛积分榜

    Args:
        competition: 联赛代码 (PL=英超, PD=西甲, BL1=德甲, SA=意甲, FL1=法甲)
    """
    try:
        result = api.get_standings(competition)
        parsed = _parse_standings(result, competition)

        if not parsed.get("standings"):
            return {"standings": [], "message": "暂无积分榜数据", "source": api.NAME}

        parsed["source"] = api.NAME
        return parsed
    except Exception as e:
        return {"error": str(e), "standings": []}


# ============================================================
# 工具 4: 球队信息
# ============================================================

async def get_team_info(team_name: str) -> dict:
    """获取球队的详细信息和分析

    Args:
        team_name: 球队名称 (英文, 如 'Arsenal', 'Manchester City')
    """
    elo = EloSystem.get_elo(team_name)
    elo_tier = (
        "世界顶级" if elo >= 1850
        else "欧洲一流" if elo >= 1750
        else "欧洲二流" if elo >= 1600
        else "中游水平" if elo >= 1450
        else "下游保级"
    )

    # 尝试从 API 获取真实信息
    team_id = _resolve_team_id(team_name)
    api_info = None
    if team_id and isinstance(api, APIFootballClient):
        try:
            api_info = api.get_team_info(team_id)
        except Exception:
            pass

    return {
        "name": team_name,
        "team_id": team_id,
        "elo_rating": elo,
        "elo_tier": elo_tier,
        "api_info": api_info,
        "analysis": (
            f"{team_name} 当前 ELO 评分为 {elo}，属于{elo_tier}水平。"
        ),
        "source": api.NAME if api_info else "ELO数据库",
    }


# ============================================================
# 工具 5: 历史交锋分析
# ============================================================

async def analyze_head_to_head(
    team_a: str, team_b: str, matches: list[dict] | None = None
) -> dict:
    """分析两队历史交锋记录

    Args:
        team_a: 球队 A 名称
        team_b: 球队 B 名称
        matches: 历史交锋数据 (可选, 无数据时将使用模拟数据)
    """
    if matches is None:
        import random
        # 模拟基于 ELO 的合理数据
        elo_a = EloSystem.get_elo(team_a)
        elo_b = EloSystem.get_elo(team_b)
        advantage = (elo_a - elo_b) / 400.0

        a_wins = max(2, int(5 + advantage * 3))
        b_wins = max(2, int(5 - advantage * 3))
        draws = max(2, 10 - a_wins - b_wins)
        matches = []
        for _ in range(a_wins):
            matches.append({"result": "A_WIN", "home": team_a, "away": team_b})
        for _ in range(b_wins):
            matches.append({"result": "B_WIN", "home": team_a, "away": team_b})
        for _ in range(draws):
            matches.append({"result": "DRAW", "home": team_a, "away": team_b})

    total = len(matches)
    a_wins = sum(1 for m in matches if m["result"] == "A_WIN")
    b_wins = sum(1 for m in matches if m["result"] == "B_WIN")
    draws = sum(1 for m in matches if m["result"] == "DRAW")

    return {
        "team_a": team_a,
        "team_b": team_b,
        "total_matches": total,
        "team_a_wins": a_wins,
        "team_b_wins": b_wins,
        "draws": draws,
        "team_a_win_rate": f"{a_wins / total * 100:.1f}%" if total > 0 else "N/A",
        "team_b_win_rate": f"{b_wins / total * 100:.1f}%" if total > 0 else "N/A",
        "summary": (
            f"{team_a} 在近 {total} 次交锋中取得 {a_wins} 胜 {draws} 平 {b_wins} 负，"
            f"胜率 {a_wins / total * 100:.1f}%"
        ) if total > 0 else "暂无交锋记录",
    }


# ============================================================
# 工具 6: 知识库检索 (RAG)
# ============================================================

async def search_knowledge_base(query: str, top_k: int = 5) -> dict[str, Any]:
    """搜索足球战术知识库

    从向量数据库中检索与查询相关的战术分析文章、比赛复盘、
    教练访谈等专业内容。

    Args:
        query: 搜索查询 (自然语言)
        top_k: 返回文档数量
    """
    try:
        from src.rag.retriever import get_retriever

        retriever = get_retriever()
        results = retriever.search(query, top_k=top_k)

        if not results:
            return {
                "query": query,
                "results": [],
                "message": "知识库中未找到相关内容。可尝试更通用的查询词，或向知识库添加更多文档。",
            }

        return {
            "query": query,
            "total_found": len(results),
            "results": [
                {
                    "content": r["content"],
                    "relevance": r["relevance"],
                    "source": r.get("source", "unknown"),
                    "author": r.get("author", ""),
                    "date": r.get("date", ""),
                    "category": r.get("category", ""),
                    "tags": r.get("tags", ""),
                }
                for r in results
            ],
            "instruction": "请将这些知识库内容作为分析的理论支撑，结合实时数据给出专业判断。必须引用来源和日期。",
        }
    except Exception as e:
        return {
            "query": query,
            "error": f"知识库检索失败: {e}",
            "results": [],
        }
        # 模拟基于 ELO 的合理数据
        import random
        elo_a = EloSystem.get_elo(team_a)
        elo_b = EloSystem.get_elo(team_b)
        advantage = (elo_a - elo_b) / 400.0

        a_wins = max(2, int(5 + advantage * 3))
        b_wins = max(2, int(5 - advantage * 3))
        draws = max(2, 10 - a_wins - b_wins)
        matches = []
        for _ in range(a_wins):
            matches.append({"result": "A_WIN", "home": team_a, "away": team_b})
        for _ in range(b_wins):
            matches.append({"result": "B_WIN", "home": team_a, "away": team_b})
        for _ in range(draws):
            matches.append({"result": "DRAW", "home": team_a, "away": team_b})

    total = len(matches)
    a_wins = sum(1 for m in matches if m["result"] == "A_WIN")
    b_wins = sum(1 for m in matches if m["result"] == "B_WIN")
    draws = sum(1 for m in matches if m["result"] == "DRAW")

    return {
        "team_a": team_a,
        "team_b": team_b,
        "total_matches": total,
        "team_a_wins": a_wins,
        "team_b_wins": b_wins,
        "draws": draws,
        "team_a_win_rate": f"{a_wins / total * 100:.1f}%" if total > 0 else "N/A",
        "team_b_win_rate": f"{b_wins / total * 100:.1f}%" if total > 0 else "N/A",
        "summary": (
            f"{team_a} 在近 {total} 次交锋中取得 {a_wins} 胜 {draws} 平 {b_wins} 负，"
            f"胜率 {a_wins / total * 100:.1f}%"
        ) if total > 0 else "暂无交锋记录",
    }


# ============================================================
# 工具 7: 实时比分
# ============================================================

async def get_live_scores(league: str | None = None, team: str | None = None) -> dict[str, Any]:
    """获取当前进行中的比赛实时比分

    Args:
        league: 联赛筛选 (如 '英超', '西甲'), 不填返回全部
        team:   球队筛选, 不填返回全部
    """
    try:
        if isinstance(api, APIFootballClient):
            fixtures_data = api._get("fixtures", {"live": "all"})
            matches = []
            for f in fixtures_data.get("response", []):
                fixt = f.get("fixture", {})
                teams_data = f.get("teams", {})
                goals = f.get("goals", {})
                league_info = f.get("league", {})
                status_info = fixt.get("status", {})

                ln = league_info.get("name", "")
                if league and league not in ln:
                    continue
                hn = teams_data.get("home", {}).get("name", "")
                an = teams_data.get("away", {}).get("name", "")
                if team and team not in hn and team not in an:
                    continue

                matches.append({
                    "id": fixt.get("id"),
                    "status": status_info.get("short", "?"),
                    "elapsed": status_info.get("elapsed", 0),
                    "home_team": hn, "away_team": an,
                    "score": f"{goals.get('home', 0)} - {goals.get('away', 0)}",
                    "competition": ln,
                })

            if not matches:
                return {"live_matches": [], "message": "当前没有进行中的比赛"}
            matches.sort(key=lambda m: m["elapsed"], reverse=True)
            return {"live_matches": matches, "total": len(matches), "source": api.NAME}
        else:
            return {"live_matches": [], "message": "实时比分需要 API-Football (RapidAPI)", "source": api.NAME}
    except Exception as e:
        return {"error": str(e), "live_matches": []}


# ============================================================
# 工具 8: 近N场xG计算
# ============================================================

async def calculate_recent_xg(
    team_name: str,
    matches: int = 5,
    league: str = "PL",
) -> dict[str, Any]:
    """计算球队近N场场均xG (基于射门统计估算)

    Args:
        team_name: 球队名称
        matches:   统计最近几场 (默认 5)
        league:    联赛代码
    """
    # 查找球队ID
    team_id = _resolve_team_id(team_name)
    if team_id is None:
        return {"error": f"未找到球队: {team_name}"}

    try:
        # 如果使用 API-Football，尝试获取真实比赛统计
        if isinstance(api, APIFootballClient):
            league_id_map = {"PL": 39, "PD": 140, "BL1": 78, "SA": 135, "FL1": 61}
            league_id = league_id_map.get(league.upper(), 39)
            fixtures_raw = api._get("fixtures", {"team": team_id, "last": matches})
            fixtures = fixtures_raw.get("response", [])
        else:
            fixtures = []
    except Exception:
        fixtures = []

    if not fixtures:
        # 降级：基于 ELO 估算
        from src.models.elo import EloSystem
        elo = EloSystem.get_elo(team_name)
        s = (elo - 1500) / 400.0
        import random
        rng = random.Random(hash(team_name) % 2**32)
        base_xg = 1.0 + s * 0.8
        match_data = []
        for i in range(matches):
            xg = round(base_xg + rng.uniform(-0.4, 0.4), 3)
            xga = round(1.2 - s * 0.4 + rng.uniform(-0.3, 0.3), 3)
            match_data.append({"match": f"近{matches}场第{i+1}场", "xg": xg, "xga": xga, "method": "ELO估算"})
        avg_xg = sum(m["xg"] for m in match_data) / len(match_data)
        return {
            "team": team_name, "period": f"近{matches}场",
            "average_xg": round(avg_xg, 3),
            "match_details": match_data,
            "note": "⚠️ ELO估算 —— 配置 API-Football 获取真实xG",
        }

    # 解析真实比赛数据
    match_list = []
    valid = 0
    for f in fixtures:
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        is_home = teams.get("home", {}).get("id") == team_id
        gf = (goals.get("home") or 0) if is_home else (goals.get("away") or 0)
        ga = (goals.get("away") or 0) if is_home else (goals.get("home") or 0)

        # 从统计数据估算 xG
        stats_list = f.get("statistics", [])
        team_stats = {}
        for ts in stats_list:
            if ts.get("team", {}).get("id") == team_id:
                for stat in ts.get("statistics", []):
                    key = stat.get("type", "").lower().replace(" ", "_")
                    val = stat.get("value")
                    if isinstance(val, str) and val.endswith("%"):
                        val = val.replace("%", "")
                    try:
                        team_stats[key] = float(val) if val is not None else 0.0
                    except (ValueError, TypeError):
                        team_stats[key] = 0.0
                break

        sot = team_stats.get("shots_on_target", 0)
        total_shots = team_stats.get("total_shots", 0)
        shots_off = max(0, total_shots - sot)
        corners = team_stats.get("corner_kicks", 0)
        xg_est = sot * 0.28 + shots_off * 0.04 + corners * 0.02 + 0.1
        xg_est = max(xg_est, 0.05)
        opp_name = teams.get("away", {}).get("name", "") if is_home else teams.get("home", {}).get("name", "")

        match_list.append({
            "date": f.get("fixture", {}).get("date", "")[:10],
            "opponent": opp_name,
            "venue": "主场" if is_home else "客场",
            "result": f"{gf}-{ga}",
            "goals_for": gf, "goals_against": ga,
            "xg": round(xg_est, 3), "xga": round(xg_est * 0.75, 3),
            "shots": int(total_shots), "shots_on_target": int(sot),
        })
        valid += 1

    if valid == 0:
        return {"error": f"未找到 {team_name} 近{matches}场可解析的比赛数据"}

    avg_xg = sum(m["xg"] for m in match_list) / valid
    avg_xga = sum(m["xga"] for m in match_list) / valid
    avg_gf = sum(m["goals_for"] for m in match_list) / valid

    finishing = "高效" if avg_gf > avg_xg + 0.3 else ("低效" if avg_gf < avg_xg - 0.3 else "正常")

    return {
        "team": team_name, "team_id": team_id,
        "period": f"近{valid}场",
        "average_xg": round(avg_xg, 3),
        "average_xga": round(avg_xga, 3),
        "average_xg_diff": round(avg_xg - avg_xga, 3),
        "average_goals": round(avg_gf, 2),
        "finishing_assessment": finishing,
        "match_details": match_list,
        "method": "代理xG(射正×0.28+射偏×0.04+角球×0.02)",
    }


# ============================================================
# 工具 9: 球队雷达图
# ============================================================

async def generate_radar_chart(
    team_name: str,
    compare_with: str | None = None,
    league: str = "PL",
    output_format: str = "dict",
) -> dict[str, Any]:
    """生成球队能力六维雷达图

    Args:
        team_name:    球队名称
        compare_with: 对比球队 (可选)
        league:       联赛代码
        output_format: "dict" 返回数据, "base64" 返回 PNG 图片
    """
    # 构建数据
    team_data = await _build_radar_data(team_name, league)
    compare_data = None
    if compare_with:
        compare_data = await _build_radar_data(compare_with, league)

    if output_format == "dict":
        result: dict[str, Any] = {"team": team_data}
        if compare_data:
            result["compare"] = compare_data
        return result

    # base64 图片模式 —— 需要 matplotlib
    try:
        import base64
        import io

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return {"error": "请安装 matplotlib: pip install matplotlib", "team": team_data}

    categories = ["进攻火力", "防守稳固", "控球组织", "纪律性", "终结效率", "近期状态"]
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist() + [0]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    values = [team_data["attack"], team_data["defense"], team_data["possession"],
              team_data["discipline"], team_data["efficiency"], team_data["form"], team_data["attack"]]
    ax.fill(angles, values, alpha=0.25, color="#38bdf8")
    ax.plot(angles, values, "o-", linewidth=2, color="#38bdf8", label=team_data["name"])

    if compare_data:
        cvals = [compare_data["attack"], compare_data["defense"], compare_data["possession"],
                 compare_data["discipline"], compare_data["efficiency"], compare_data["form"], compare_data["attack"]]
        ax.fill(angles, cvals, alpha=0.20, color="#f472b6")
        ax.plot(angles, cvals, "s--", linewidth=2, color="#f472b6", label=compare_data["name"])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color="white", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 100)
    ax.set_yticklabels(["20", "40", "60", "80", "100"], color="#94a3b8", fontsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")
    ax.grid(color="#334155", linewidth=0.5)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1),
              facecolor="#1e293b", edgecolor="#334155", labelcolor="white")
    title = f"⚽ {team_data['name']}"
    if compare_data:
        title += f"  vs  {compare_data['name']}"
    ax.set_title(title, color="white", fontsize=14, fontweight="bold", pad=20)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=120, facecolor="#0f172a", bbox_inches="tight")
    plt.close()
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode()

    result = {"team": team_data, "chart_base64": img_base64, "chart_mime": "image/png"}
    if compare_data:
        result["compare"] = compare_data
    return result


async def _build_radar_data(team_name: str, league: str) -> dict[str, Any]:
    """构建雷达图六维数据"""
    from src.models.elo import EloSystem
    elo = EloSystem.get_elo(team_name)
    strength = (elo - 1500) / 400.0

    # 尝试获取真实统计
    stats = None
    team_id = _resolve_team_id(team_name)
    if team_id and isinstance(api, APIFootballClient):
        try:
            league_id_map = {"PL": 39, "PD": 140, "BL1": 78, "SA": 135, "FL1": 61}
            league_id = league_id_map.get(league.upper(), 39)
            stats = api.get_team_statistics(team_id, league_id)
        except Exception:
            stats = None

    if stats and stats.get("played", 0) > 0:
        gf = stats.get("goals_for_avg", 1.4)
        ga = stats.get("goals_against_avg", 1.2)
        played = max(stats.get("played", 1), 1)
        wins = stats.get("wins", 0)
        draws = stats.get("draws", 0)
        return {
            "name": team_name, "team_id": team_id,
            "attack": round(min(100, gf / 3.0 * 100), 1),
            "defense": round(min(100, (2.5 - ga) / 2.5 * 100), 1),
            "possession": round(min(100, 55 + strength * 5), 1),
            "discipline": round(min(100, 50 - strength * 10), 1),
            "efficiency": round(min(100, (gf / max(gf + 0.3, 0.1)) * 60), 1),
            "form": round(min(100, (wins + draws * 0.5) / played * 100), 1),
            "data_source": "API-Football",
        }
    else:
        return {
            "name": team_name, "team_id": team_id,
            "attack": round(min(100, 45 + strength * 35), 1),
            "defense": round(min(100, 45 + strength * 30), 1),
            "possession": round(min(100, 48 + strength * 25), 1),
            "discipline": round(min(100, 50 - strength * 15), 1),
            "efficiency": round(min(100, 50 + strength * 20), 1),
            "form": round(min(100, 50 + strength * 25), 1),
            "data_source": "ELO估算",
        }


# ============================================================
# 工具 10: 获取比赛赔率
# ============================================================

async def get_match_odds(
    home_team: str,
    away_team: str,
    competition: str = "PL",
) -> dict[str, Any]:
    """获取比赛赔率数据 (欧赔 + 必发指数)

    从 API-Football /odds 端点拉取多家博彩公司赔率,
    计算平均赔率、隐含概率、margin 剥离后的真实概率。

    Args:
        home_team:   主队名称
        away_team:   客队名称
        competition: 联赛代码
    """
    # 1. 先搜索比赛
    try:
        result = api.get_matches(competition=competition, status="NS")
        matches = result.get("matches", [])
    except Exception:
        matches = []

    # 匹配球队
    fixture_id = None
    home_match = away_match = None
    for m in matches:
        if (home_team.lower() in m.get("home_team", "").lower()
            and away_team.lower() in m.get("away_team", "").lower()):
            fixture_id = m.get("id")
            home_match = m["home_team"]
            away_match = m["away_team"]
            break

    if fixture_id is None:
        # 未找到比赛，返回模拟赔率
        return _mock_odds(home_team, away_team)

    # 2. 拉取赔率
    if not isinstance(api, APIFootballClient):
        return _mock_odds(home_team, away_team)

    try:
        odds_data = api._get("odds", {"fixture": fixture_id})
        bookmakers = odds_data.get("response", [])
    except Exception as e:
        logger.warning(f"赔率 API 请求失败: {e}")
        return _mock_odds(home_team, away_team)

    if not bookmakers:
        return _mock_odds(home_team, away_team, note="该比赛暂无赔率数据")

    # 3. 解析赔率
    from src.models.odds_analyzer import OddsLine, calculate_implied_probability

    odds_list: list[OddsLine] = []
    betfair_odds = None

    for bm in bookmakers:
        name = bm.get("name", "Unknown")
        bets = bm.get("bets", [])
        # 找 Match Winner 盘口
        for bet in bm.get("bets", []):
            if bet.get("name") == "Match Winner":
                values = bet.get("values", [])
                if len(values) >= 3:
                    odds_map = {}
                    for v in values:
                        odds_map[v.get("value", "")] = float(v.get("odd", 1.0))

                    line = OddsLine(
                        bookmaker=name,
                        home=odds_map.get("Home", 1.0),
                        draw=odds_map.get("Draw", 1.0),
                        away=odds_map.get("Away", 1.0),
                        updated=str(bm.get("update", "")),
                        is_exchange=("betfair" in name.lower() or "exchange" in name.lower()),
                    )

                    if line.is_exchange:
                        betfair_odds = line

                    # 过滤异常赔率
                    if line.home >= 1.05 and line.draw >= 1.05 and line.away >= 1.05:
                        odds_list.append(line)
                break

    if not odds_list:
        return _mock_odds(home_team, away_team, note="无有效赔率数据")

    # 4. 计算市场隐含概率 (使用 Shin 方法更精确)
    avg_home = sum(o.home for o in odds_list) / len(odds_list)
    avg_draw = sum(o.draw for o in odds_list) / len(odds_list)
    avg_away = sum(o.away for o in odds_list) / len(odds_list)

    implied = calculate_implied_probability(avg_home, avg_draw, avg_away, method="shin")

    # 5. 最佳赔率 (每项选最高)
    best_home_odds = max(o.home for o in odds_list)
    best_draw_odds = max(o.draw for o in odds_list)
    best_away_odds = max(o.away for o in odds_list)

    # 6. 必发指数 (如果有 Betfair 交易所数据)
    bf_index = None
    if betfair_odds:
        # 没有真实成交量时用赔率反推
        bf_implied = calculate_implied_probability(
            betfair_odds.home, betfair_odds.draw, betfair_odds.away, method="shin"
        )
        bf_index = {
            "home_index": round(bf_implied.home * 100, 1),
            "draw_index": round(bf_implied.draw * 100, 1),
            "away_index": round(bf_implied.away * 100, 1),
            "source": f"Betfair 赔率反推 (margin={bf_implied.margin*100:.1f}%)",
        }

    return {
        "fixture_id": fixture_id,
        "home_team": home_match or home_team,
        "away_team": away_match or away_team,
        "bookmaker_count": len(odds_list),
        "market_consensus": {
            "avg_odds": {"home": round(avg_home, 2), "draw": round(avg_draw, 2), "away": round(avg_away, 2)},
            "best_odds": {"home": best_home_odds, "draw": best_draw_odds, "away": best_away_odds},
            "implied_probability": {
                "home": f"{implied.home * 100:.1f}%",
                "draw": f"{implied.draw * 100:.1f}%",
                "away": f"{implied.away * 100:.1f}%",
            },
            "market_margin": f"{implied.margin * 100:.1f}%",
            "market_favorite": (
                "主胜" if implied.home >= implied.draw and implied.home >= implied.away
                else "平局" if implied.draw >= implied.home and implied.draw >= implied.away
                else "客胜"
            ),
        },
        "betfair_index": bf_index,
        "bookmaker_breakdown": [
            {"name": o.bookmaker, "home": o.home, "draw": o.draw, "away": o.away}
            for o in odds_list[:10]
        ],
        "source": "API-Football",
    }


def _mock_odds(home_team: str, away_team: str, note: str = "") -> dict:
    """模拟赔率 (无 API Key 降级)"""
    from src.models.elo import EloSystem

    elo_home = EloSystem.get_elo(home_team)
    elo_away = EloSystem.get_elo(away_team)
    gap = elo_home - elo_away + EloSystem.HOME_ADVANTAGE

    # ELO 差值 → 赔率 (经验映射)
    p_home = 1.0 / (1.0 + 10 ** (-gap / 400.0))
    # 加上 margin
    margin = 1.06
    home_odds = round(margin / p_home, 2) if p_home > 0 else 1.5
    away_odds = round(margin / (1 - p_home) * (p_home / (1 - p_home + 0.1)), 2) if (1 - p_home) > 0 else 3.5
    draw_odds = round((home_odds + away_odds) / 3.5, 2)
    home_odds = max(home_odds, 1.05)
    draw_odds = max(draw_odds, 1.05)
    away_odds = max(away_odds, 1.05)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "bookmaker_count": 0,
        "market_consensus": {
            "avg_odds": {"home": home_odds, "draw": draw_odds, "away": away_odds},
            "implied_probability": {
                "home": f"{1 / home_odds / (1 / home_odds + 1 / draw_odds + 1 / away_odds) * 100:.1f}%",
                "draw": f"{1 / draw_odds / (1 / home_odds + 1 / draw_odds + 1 / away_odds) * 100:.1f}%",
                "away": f"{1 / away_odds / (1 / home_odds + 1 / draw_odds + 1 / away_odds) * 100:.1f}%",
            },
            "market_margin": f"{((1 / home_odds + 1 / draw_odds + 1 / away_odds) - 1) * 100:.1f}%",
        },
        "betfair_index": None,
        "note": f"⚠️ ELO 模拟赔率 —— 配置 API-Football 获取真实赔率{(' (' + note + ')') if note else ''}",
        "source": "ELO模拟",
    }


# ============================================================
# 工具 11: 模型 vs 市场 价值对比
# ============================================================

async def compare_model_vs_market(
    home_team: str,
    away_team: str,
    competition: str = "PL",
) -> dict[str, Any]:
    """模型预测 vs 市场赔率 价值对比

    自动调用:
    1. predict_match → 模型胜平负概率
    2. get_match_odds  → 市场隐含概率 (margin 剥离后)
    3. 对比两者差异 → 检测价值投注机会

    输出:
    - 模型 vs 市场概率对比表
    - 价值方向 & 凯利投注比例
    - 必发指数偏离分析

    Args:
        home_team:   主队名称
        away_team:   客队名称
        competition: 联赛代码
    """
    # 1. 模型预测
    pred = await predict_match(home_team=home_team, away_team=away_team)
    model_home = pred["prediction"]["home_win"] / 100.0
    model_draw = pred["prediction"]["draw"] / 100.0
    model_away = pred["prediction"]["away_win"] / 100.0

    # 2. 市场赔率
    odds_result = await get_match_odds(home_team, away_team, competition)
    market = odds_result.get("market_consensus", {})

    # 解析隐含概率字符串 → 浮点数
    imp = market.get("implied_probability", {})
    mkt_home = _parse_pct(imp.get("home", "0%")) / 100.0
    mkt_draw = _parse_pct(imp.get("draw", "0%")) / 100.0
    mkt_away = _parse_pct(imp.get("away", "0%")) / 100.0

    # 3. 价值检测
    from src.models.odds_analyzer import detect_value

    value = detect_value(model_home, model_draw, model_away, mkt_home, mkt_draw, mkt_away)

    # 4. 判断
    if value.best_value == "none":
        verdict = "模型与市场一致，无明显价值偏离。建议观望。"
    elif value.confidence in ("高", "中"):
        verdict = f"模型发现价值方向: **{value.best_value}** (置信度: {value.confidence})。模型概率显著高于市场隐含概率，存在潜在价值。"
    else:
        verdict = f"模型轻微倾向 **{value.best_value}**，但偏离幅度不大，仅供参考。"

    return {
        "match": f"{home_team} vs {away_team}",
        "model_prediction": {
            "home": f"{model_home * 100:.1f}%",
            "draw": f"{model_draw * 100:.1f}%",
            "away": f"{model_away * 100:.1f}%",
            "method": "泊松(60%) + ELO(40%)",
        },
        "market_implied": {
            "home": imp.get("home", "N/A"),
            "draw": imp.get("draw", "N/A"),
            "away": imp.get("away", "N/A"),
            "margin": market.get("market_margin", "N/A"),
            "source": odds_result.get("source", "unknown"),
        },
        "value_analysis": {
            "home_value": f"{value.home_value * 100:+.1f}%",
            "draw_value": f"{value.draw_value * 100:+.1f}%",
            "away_value": f"{value.away_value * 100:+.1f}%",
            "best_value_direction": value.best_value,
            "kelly_fraction": f"{value.kelly_fraction * 100:.1f}%",
            "confidence": value.confidence,
            "verdict": verdict,
        },
        "betfair_index": odds_result.get("betfair_index"),
        "recommendation": {
            "模型推荐": pred["prediction"]["recommendation"],
            "市场看好": market.get("market_favorite", "N/A"),
            "是否一致": "✅ 一致" if pred["prediction"]["recommendation"].startswith(market.get("market_favorite", "")) else "⚠️ 分歧",
        },
    }


def _parse_pct(s: str) -> float:
    """解析百分比字符串 → 浮点数"""
    try:
        return float(s.replace("%", ""))
    except (ValueError, AttributeError):
        return 0.0


# ============================================================
# 工具 12: 复盘昨日 + 模型自校准
# ============================================================

async def review_yesterday_matches(league: str = "PL") -> dict[str, Any]:
    """复盘昨日比赛 —— 模型预测 vs 真实赛果 vs Kambi 赔率

    自动执行:
    1. 获取昨日所有完赛数据 (比分)
    2. 对每场比赛重新跑模型预测
    3. 对比实际结果, 计算 Brier Score / Log Loss / 准确率
    4. 拉取 Kambi 共识赔率进行模型 vs 市场对比
    5. 检测系统性偏差 (主场高估? 平局低估?)
    6. 生成调整建议 (ELO 主场加成系数 / 平局扩展因子等)

    这是模型持续改进的核心工具。建议每天赛后运行一次。

    Args:
        league: 联赛代码 (PL=英超, PD=西甲, BL1=德甲, SA=意甲, FL1=法甲)
    """
    from src.models.backtest import review_and_adjust

    try:
        result = await review_and_adjust(league)
        return result
    except Exception as e:
        logger.error(f"复盘失败: {e}")
        return {
            "error": str(e),
            "message": "复盘需要 API-Football (RapidAPI) 获取昨日真实赛果",
            "alternative": "可手动传入比赛数据调用 backtest_match 工具",
        }


async def backtest_match(
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
) -> dict[str, Any]:
    """单场比赛回测 —— 检查模型预测是否准确

    输入实际赛果，对比模型预测，输出偏差分析。

    Args:
        home_team:   主队名称
        away_team:   客队名称
        home_goals:  主队实际进球
        away_goals:  客队实际进球
    """
    # 1. 跑模型预测
    pred = await predict_match(home_team=home_team, away_team=away_team)

    model_h = pred["prediction"]["home_win"] / 100.0
    model_d = pred["prediction"]["draw"] / 100.0
    model_a = pred["prediction"]["away_win"] / 100.0

    # 2. 实际结果
    if home_goals > away_goals:
        actual = "H"
        actual_label = "主胜"
    elif away_goals > home_goals:
        actual = "A"
        actual_label = "客胜"
    else:
        actual = "D"
        actual_label = "平局"

    # 3. 正确性
    pick = max((model_h, "H"), (model_d, "D"), (model_a, "A"))[1]
    correct = (pick == actual)

    # 4. 偏差
    import math
    actual_prob = {"H": model_h, "D": model_d, "A": model_a}[actual]
    actual_prob = max(actual_prob, 1e-10)

    actual_vec = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}[actual]
    brier = (model_h - actual_vec[0]) ** 2 + (model_d - actual_vec[1]) ** 2 + (model_a - actual_vec[2]) ** 2

    # 比分预测
    top_score = pred["likely_scores"][0]["score"] if pred["likely_scores"] else "?"
    score_correct = (top_score == f"{home_goals}-{away_goals}")

    return {
        "match": f"{home_team} vs {away_team}",
        "actual_result": f"{home_goals}-{away_goals} ({actual_label})",
        "model_prediction": {
            "home": f"{model_h * 100:.1f}%",
            "draw": f"{model_d * 100:.1f}%",
            "away": f"{model_a * 100:.1f}%",
            "pick": pick,
            "correct": "✅" if correct else "❌",
        },
        "score_prediction": {
            "predicted": top_score,
            "actual": f"{home_goals}-{away_goals}",
            "correct": "✅" if score_correct else "❌",
        },
        "metrics": {
            "brier_score": round(brier, 4),
            "log_loss": round(-math.log(actual_prob), 4),
            "confidence_on_correct_outcome": f"{actual_prob * 100:.1f}%",
        },
        "analysis": (
            f"模型{'正确' if correct else '错误'}预测了本场方向。"
            f"实际结果为{actual_label}，模型对该结果的预测概率为{actual_prob:.0%}。"
            f"预期比分 {pred['expected_goals']['home']}-{pred['expected_goals']['away']}，"
            f"实际比分 {home_goals}-{away_goals}。"
        ),
    }


# ============================================================
# 辅助函数
# ============================================================

def _calc_form_points(form: list[str]) -> float:
    """计算近期状态积分 (场均)"""
    points = {"W": 3, "D": 1, "L": 0}
    total = sum(points.get(r.upper(), 1) for r in form)
    return total / len(form) if form else 1.5


def _resolve_team_id(team_name: str) -> int | None:
    """根据球队名称查找 ID

    先在模拟数据中搜索, 再尝试 API-Football 搜索
    """
    from src.data.api_client import MockFootballAPI

    # 先在已知球队中精确匹配
    mock = MockFootballAPI()
    name_lower = team_name.lower().strip()
    for t in mock.PREMIER_LEAGUE_TEAMS:
        if (t["name"].lower() == name_lower
            or t.get("shortName", "").lower() == name_lower
            or t.get("tla", "").lower() == name_lower):
            return t["id"]

    # 模糊匹配
    for t in mock.PREMIER_LEAGUE_TEAMS:
        if name_lower in t["name"].lower():
            return t["id"]

    # 如果是真实 API, 尝试搜索
    if isinstance(api, APIFootballClient):
        try:
            results = api.search_teams(team_name)
            if results:
                return results[0]["id"]
        except Exception:
            pass

    return None


def _parse_standings(data: dict, competition: str) -> dict:
    """解析积分榜数据, 兼容多种 API 格式

    API-Football 格式:
      {"response": [{"league": {"standings": [[...]]}}]}
    football-data.org 格式:
      {"standings": [{"table": [...]}]}
    """
    # 尝试 API-Football 格式
    response = data.get("response", [])
    if response:
        league_info = response[0].get("league", {})
        table = league_info.get("standings", [[]])[0]
        simplified = []
        for row in table:
            all_stats = row.get("all", {})
            home_stats = row.get("home", {})
            away_stats = row.get("away", {})
            simplified.append({
                "position": row.get("rank"),
                "team": row.get("team", {}).get("name", ""),
                "team_id": row.get("team", {}).get("id"),
                "played": all_stats.get("played"),
                "won": all_stats.get("win"),
                "draw": all_stats.get("draw"),
                "lost": all_stats.get("lose"),
                "goals_for": all_stats.get("goals", {}).get("for"),
                "goals_against": all_stats.get("goals", {}).get("against"),
                "goal_diff": row.get("goalsDiff"),
                "points": row.get("points"),
                "form": row.get("form"),
                # 主客场细分
                "home_won": home_stats.get("win"),
                "away_won": away_stats.get("win"),
            })
        return {"competition": league_info.get("name", competition), "standings": simplified}

    # 尝试 football-data.org 格式
    standings = data.get("standings", [])
    if standings and standings[0].get("table"):
        table = standings[0]["table"]
        simplified = []
        for row in table:
            simplified.append({
                "position": row.get("position"),
                "team": row.get("team", {}).get("name", ""),
                "played": row.get("playedGames"),
                "won": row.get("won"),
                "draw": row.get("draw"),
                "lost": row.get("lost"),
                "goals_for": row.get("goalsFor"),
                "goals_against": row.get("goalsAgainst"),
                "goal_diff": row.get("goalsFor", 0) - row.get("goalsAgainst", 0),
                "points": row.get("points"),
                "form": row.get("form"),
            })
        return {"competition": data.get("competition", {}).get("name", competition), "standings": simplified}

    return {"standings": [], "message": "无法解析积分榜数据"}
