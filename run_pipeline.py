#!/usr/bin/env python3
"""
足球预测主管线 · 一条命令跑通全部模块

用法:
  python run_pipeline.py --phase morning    # 早盘: 拉赔率 + 初筛
  python run_pipeline.py --phase afternoon  # 午盘: 蒸汽检测 + 更新
  python run_pipeline.py --phase final      # 终盘: 五基→DC→基线→best_bets→HTML

管线流程 (终盘):
  Kambi赔率 → Shin去水 → ELO查分 → 冷启动替补
  → 五基并行(B0/B1+/B2-RC/P_CANDIDATE/Xalpha)
  → Dixon-Coles ρ修正 → 联赛基线对比
  → best_bets筛选 → 深盘规则检查 → 六维预测 → HTML输出

此前所有"写了但没用"的模块现在全部接入:
  ✅ five_bases.py      ✅ dixon_coles.py     ✅ best_bets.py
  ✅ baseline.py        ✅ evaluation.py      ✅ cold_start.py
  ✅ league_profiles.py ✅ odds_analyzer.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 项目根目录 ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── 模型层 (现在全部接入) ─────────────────────────────────
from src.models.elo import EloSystem
from src.models.league_profiles import LEAGUE_PROFILES, LeagueProfile, get_profile
from src.models.five_bases import run_five_bases
from src.models.dixon_coles import dc_marginals
from src.models.baseline import baseline_predict
from src.models.best_bets import recommend_bets, THRESHOLDS
from src.models.cold_start import ColdStartEngine
from src.models.odds_analyzer import calculate_implied_probability

# ── 数据层 ─────────────────────────────────────────────
from src.data.team_registry import TEAM_REGISTRY, resolve_team

# ── 日志 ───────────────────────────────────────────────
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")


# ══════════════════════════════════════════════════════════════
# 联赛名称 → 联赛代码 映射
# Kambi API 返回的联赛名 → 我们的 league_profiles 代码
# ══════════════════════════════════════════════════════════════

LEAGUE_NAME_MAP: list[tuple[str, str, str]] = [
    # (关键词, 联赛代码, 联赛名备注)
    # 顺序很重要: 更具体的匹配放前面, 防止 EFL Cup 被 "england" 误匹配

    # ── 英格兰各级别 (从低到高, 避免误匹配) ──
    ("EFL Cup", "ELC", "英联杯 → 用英冠画像(近似)"),
    ("League One", "ELC", "英甲 → 用英冠画像"),
    ("League Two", "ELC", "英乙 → 用英冠画像"),
    ("National League", "ELC", "英议联 → 用英冠画像"),
    ("Premier League", "PL", "英超"),
    ("England - Championship", "ELC", "英冠"),

    # ── 欧洲五大联赛 ──
    ("La Liga", "PD", "西甲"),
    ("Primera División", "PD", "西甲"),
    ("Spain", "PD", "西甲"),
    ("Bundesliga", "BL1", "德甲"),
    ("2. Bundesliga", "BL2", "德乙"),
    ("3. Liga", "BL2", "德丙 → 用德乙画像"),
    ("Germany", "BL1", "德甲"),
    ("Serie A", "SA", "意甲"),
    ("Italy", "SA", "意甲"),
    ("Ligue 1", "FL1", "法甲"),
    ("Ligue 2", "FL1", "法乙 → 用法甲画像(近似)"),
    ("France", "FL1", "法甲"),

    # ── 二级联赛 ──
    ("Championship", "ELC", "英冠"),
    ("Eredivisie", "DED", "荷甲"),
    ("Eerste Divisie", "DED", "荷乙 → 用荷甲画像"),
    ("Primeira Liga", "PPL", "葡超"),
    ("Liga Portugal", "PPL", "葡超"),
    ("Portugal", "PPL", "葡超"),

    # ── 欧战 ──
    ("Champions League Qual", "CLQ", "欧冠资格赛"),
    ("Champions League", "CL", "欧冠"),
    ("UEFA Champions League", "CL", "欧冠"),
    ("Europa League Qual", "CLQ", "欧联资格赛"),
    ("Europa League", "EL", "欧联"),
    ("UEFA Europa League", "EL", "欧联"),
    ("Conference League Qual", "CLQ", "欧协联资格赛"),
    ("Conference League", "CLQ", "欧协联"),
    ("UEFA Europa Conference League", "CLQ", "欧协联"),

    # ── 其他欧洲联赛 ──
    ("Eliteserien", "NOR", "挪超"),
    ("Norway", "NOR", "挪超"),
    ("Superettan", "NOR", "瑞典超 → 用挪超画像(近似)"),
    ("Sweden", "NOR", "瑞典 → 用挪超画像"),
    ("Denmark", "DEN", "丹超"),
    ("Superligaen", "DEN", "丹超"),
    ("Czechia", "CZE", "捷甲"),
    ("1. Liga", "CZE", "捷甲"),
    ("Austria", "AUT", "奥甲"),
    ("Poland", "POL", "波甲"),
    ("Ekstraklasa", "POL", "波甲"),
    ("Switzerland", "SWI", "瑞士超"),
    ("Romania", "ROM", "罗甲"),
    ("Bulgaria", "BUL", "保甲"),
    ("Hungary", "HUN", "匈甲"),
    ("NB I", "HUN", "匈甲"),
    ("Scotland", "SCO", "苏超"),

    # ── 美洲 ──
    ("Leagues Cup", "LC", "北美联杯"),
    ("MLS", "MLS", "美职联"),
    ("Major League Soccer", "MLS", "美职联"),
    ("Liga MX", "LIGA_MX", "墨超"),
    ("Mexico", "LIGA_MX", "墨超"),
    ("Brasileirão", "BSA", "巴甲"),
    ("Brasileiro", "BSA", "巴甲"),
    ("Brazil", "BSA", "巴甲"),
    ("Argentina", "ARG", "阿甲"),
    ("Colombia", "COL", "哥甲"),
    ("Chile", "CHI", "智利甲"),
    ("Ecuador", "ECU", "厄甲"),
    ("Paraguay", "PAR", "巴甲 → 用巴甲画像"),
    ("Peru", "PER", "秘甲"),
    ("Uruguay", "URU", "乌甲"),
    ("Bolivia", "BOL", "玻甲"),

    # ── 亚洲 ──
    ("J1 League", "J1", "J联赛"),
    ("Japan", "J1", "J联赛"),
    ("CSL", "CSL", "中超"),
    ("China", "CSL", "中超"),
    ("K League", "KLEAGUE", "K联赛"),
    ("Korea", "KLEAGUE", "K联赛"),

    # ── 友谊赛 ──
    ("Friendly", "DEFAULT", "友谊赛"),
]


def map_league(kambi_league_name: str) -> str:
    """将Kambi联赛名映射到我们的联赛代码"""
    name_lower = kambi_league_name.lower().strip()

    # 按顺序匹配 (具体→通用)
    for keyword, code, _desc in LEAGUE_NAME_MAP:
        if keyword.lower() in name_lower:
            return code

    # 检查是否包含"qualification" → 资格赛
    if "qualif" in name_lower:
        return "CLQ"

    logger.warning(f"  未匹配联赛: '{kambi_league_name}' → 使用通用画像")
    return "DEFAULT"


# ══════════════════════════════════════════════════════════════
# ELO → 攻防力转换
# ══════════════════════════════════════════════════════════════

def elo_to_strength(elo: float, league_elo_base: float = 1500) -> dict[str, float]:
    """ELO 评分 → 攻防力指数

    经验映射:
      ELO 高 → attack↑  defense↓ (<1 = 好防守)
      league_elo_base: 该联赛的ELO基准值 (如CLQ=1500, PL=1600)
    """
    s = (elo - league_elo_base) / 400.0
    return {
        "attack": round(max(0.3, 1.0 + s * 0.6), 2),
        "defense": round(max(0.3, 1.0 - s * 0.5), 2),
    }


def resolve_team_strength(team_name: str, league_code: str,
                          cold_engine: ColdStartEngine | None = None) -> dict[str, Any]:
    """解析球队攻防力: ELO优先 → team_registry替补 → 冷启动兜底

    Returns:
        {"elo": float, "attack": float, "defense": float, "source": str,
         "is_cold": bool, "team_id": str}
    """
    profile = get_profile(league_code)
    league_elo_base = profile.elo_base

    # Step 1: 尝试 ELO 数据库
    elo = EloSystem.get_elo(team_name)
    source = "ELO数据库"

    # Step 2: ELO未命中 → 尝试team_registry
    if elo == EloSystem.DEFAULT_ELO:
        resolved = resolve_team(team_name) if resolve_team else None
        if resolved:
            elo = resolved.base_elo
            source = f"球队注册表 ({resolved.team_id})"

    # Step 3: 仍未命中 → 冷启动
    is_cold = False
    if elo == EloSystem.DEFAULT_ELO and cold_engine:
        team_id = f"{league_code}_{team_name.upper().replace(' ', '_')[:20]}"
        state = cold_engine.get_state(team_id)
        if state is None:
            # 用联赛均值初始化冷启动
            state = cold_engine.init_team(team_id,
                                          tier_attack=1.0,
                                          tier_defense=1.0)
        elo = league_elo_base
        source = f"冷启动 (剩余{state.rounds_remaining}场)"
        is_cold = True

    strengths = elo_to_strength(elo, league_elo_base)

    return {
        "elo": elo,
        "attack": strengths["attack"],
        "defense": strengths["defense"],
        "source": source,
        "is_cold": is_cold,
        "team_id": f"{league_code}_{team_name.upper().replace(' ', '_')[:20]}",
    }


# ══════════════════════════════════════════════════════════════
# 深盘规则检查 (8月6日复盘教训)
# ══════════════════════════════════════════════════════════════

def check_deep_handicap(home_elo: float, away_elo: float, league_code: str,
                        implied_home: float) -> dict[str, Any]:
    """深盘风险检查

    规则:
      1. 深盘(让球>1.5)自动降一档
      2. ELO>200 + 联赛大球率<55% → 禁止-2.0以上深盘
      3. 克罗地亚/波兰/捷克联赛 → 天然小球倾向, 大球慎推

    Returns:
        {"is_deep": bool, "warning_level": "none"|"caution"|"danger",
         "recommendation": str, "auto_downgrade": bool}
    """
    profile = get_profile(league_code)
    elo_diff = home_elo - away_elo

    # 从隐含概率估算让球深度
    # implied_home > 0.70 ≈ -1.0盘, >0.78 ≈ -1.5盘, >0.85 ≈ -2.0盘
    implied_handicap_depth = 0
    if implied_home > 0.85:
        implied_handicap_depth = 2.0
    elif implied_home > 0.78:
        implied_handicap_depth = 1.5
    elif implied_home > 0.70:
        implied_handicap_depth = 1.0
    elif implied_home > 0.62:
        implied_handicap_depth = 0.5

    result = {
        "is_deep": implied_handicap_depth >= 1.5,
        "handicap_depth": implied_handicap_depth,
        "elo_diff": int(elo_diff),
        "warning_level": "none",
        "recommendation": "",
        "auto_downgrade": False,
    }

    # 深盘检查
    if implied_handicap_depth >= 1.5:
        result["warning_level"] = "caution"
        result["recommendation"] = "深盘(>1.5)自动降一档置信"
        result["auto_downgrade"] = True

    # ELO大幅领先 + 联赛小球
    if elo_diff > 200 and profile.over_25_rate < 0.55 and implied_handicap_depth >= 2.0:
        result["warning_level"] = "danger"
        result["recommendation"] = (
            f"禁止: ELO差{elo_diff}+{profile.name}大球率仅{profile.over_25_rate:.0%}, "
            f"禁止{-2.0}以上深盘 (8/6里耶卡教训)"
        )
        result["auto_downgrade"] = True

    # 低比分联赛特别检查
    low_scoring_leagues = {
        "克罗地亚": ["HNL"],
        "波兰": ["EKS"],
        "捷克": ["CZE"],
    }
    for country, codes in low_scoring_leagues.items():
        if league_code in codes and implied_handicap_depth >= 2.0:
            result["warning_level"] = "danger"
            result["recommendation"] = f"{country}联赛天然小球, 禁止深盘"

    return result


# ══════════════════════════════════════════════════════════════
# 单场完整预测 (所有模块串起来)
# ══════════════════════════════════════════════════════════════

def predict_one_match(match: dict, cold_engine: ColdStartEngine | None = None,
                      dc_rho: float = -0.10) -> dict[str, Any]:
    """对单场比赛执行完整预测管线

    输入: Kambi match dict (含 odds_1x2)
    输出: 六维预测 + 决策链 + 所有中间产物
    """
    home_name = match.get("home", "Unknown")
    away_name = match.get("away", "Unknown")
    odds_1x2 = match.get("odds_1x2", {})

    # ── Step 0: 联赛映射 ──────────────────────────────
    league_name = match.get("league", {}).get("name", "")
    league_code = map_league(league_name)
    profile = get_profile(league_code)

    logger.info(f"  {home_name} vs {away_name} [{profile.name}]")

    # ── Step 1: 攻防力解析 (ELO → 冷启动) ─────────────
    home_st = resolve_team_strength(home_name, league_code, cold_engine)
    away_st = resolve_team_strength(away_name, league_code, cold_engine)

    # ── Step 2: Shin 去水 → 市场隐含概率 ───────────────
    market_probs = None
    shin_result = None
    if odds_1x2 and all(k in odds_1x2 for k in ("home", "draw", "away")):
        shin_result = calculate_implied_probability(
            odds_1x2["home"], odds_1x2["draw"], odds_1x2["away"],
            method="shin"
        )
        market_probs = {
            "home": shin_result.home,
            "draw": shin_result.draw,
            "away": shin_result.away,
            "margin": shin_result.margin,
        }
        logger.debug(f"    Shin: H={shin_result.home:.1%} D={shin_result.draw:.1%} "
                     f"A={shin_result.away:.1%} margin={shin_result.margin:.1%}")
    else:
        logger.warning(f"    无Kambi赔率, 跳过Shin去水")

    # ── Step 3: 五基并行 ──────────────────────────────
    five_base_report = run_five_bases(
        home_team=home_name,
        away_team=away_name,
        league_code=league_code,
        home_attack=home_st["attack"],
        home_defense=home_st["defense"],
        away_attack=away_st["attack"],
        away_defense=away_st["defense"],
        home_advantage=profile.home_goal_boost,
        league_avg=profile.avg_total_goals,
        market_home_prob=market_probs["home"] if market_probs else None,
        market_draw_prob=market_probs["draw"] if market_probs else None,
        market_away_prob=market_probs["away"] if market_probs else None,
    )

    # 提取 P_CANDIDATE (自适应融合) 作为主预测
    pc = next((b for b in five_base_report.bases if b.base_name == "P_CANDIDATE"), None)
    if pc is None:
        pc = five_base_report.bases[0]  # fallback to B0

    # ── Step 4: Dixon-Coles ρ 修正 ────────────────────
    # 用 P_CANDIDATE 的 λ 跑 DC 修正
    lam_h = pc.metadata.get("lambda_home", profile.avg_home_goals)
    lam_a = pc.metadata.get("lambda_away", profile.avg_away_goals)
    # P_CANDIDATE 没有直接存 λ, 从 B0 取
    b0 = next((b for b in five_base_report.bases if b.base_name == "B0"), None)
    if b0:
        lam_h = b0.metadata.get("lambda_home", profile.avg_home_goals)
        lam_a = b0.metadata.get("lambda_away", profile.avg_away_goals)

    dc_result = dc_marginals(lam_h, lam_a, max_g=8, rho=dc_rho)

    # ── Step 5: 基线对比 ──────────────────────────────
    baseline = baseline_predict(home_name, away_name, league_code)

    # ── Step 6: 合成六维预测 ──────────────────────────
    # 维度①: 胜平负 — 融合 P_CANDIDATE + DC 修正
    pc_hw = pc.distribution.home_win
    pc_dr = pc.distribution.draw
    pc_aw = pc.distribution.away_win

    # 用DC修正后的边际 (DC在低比分上更准)
    final_home = round(pc_hw * 0.60 + dc_result["home_win"] * 0.40, 4)
    final_draw = round(pc_dr * 0.60 + dc_result["draw"] * 0.40, 4)
    final_away = round(pc_aw * 0.60 + dc_result["away_win"] * 0.40, 4)

    # 维度②: 波胆 — Top 5 从 P_CANDIDATE
    top_scores = sorted(pc.distribution.scores.items(), key=lambda x: x[1], reverse=True)[:5]

    # 维度③: 全场大小球 — 从 DC
    over_25 = dc_result["over_25"]
    over_35 = dc_result["over_35"]

    # 维度④: 半场大小球 (用42%规则估算半场 λ)
    half_lam_h = lam_h * 0.42
    half_lam_a = lam_a * 0.42
    half_dc = dc_marginals(half_lam_h, half_lam_a, max_g=6, rho=dc_rho)
    half_over_15 = half_dc["over_25"]  # 半场 threshold 是 1.5

    # 维度⑤: 半场让球 (从半场胜平负估算)
    half_hw = half_dc["home_win"]
    half_aw = half_dc["away_win"]

    # 维度⑥: 角球 — 从联赛画像
    expected_corners = profile.avg_corners
    corner_home_share = profile.corner_home_share

    # ── Step 7: 深盘检查 ──────────────────────────────
    handicap_check = check_deep_handicap(
        home_st["elo"], away_st["elo"], league_code,
        market_probs["home"] if market_probs else pc_hw
    )

    # ── Step 8: best_bets 筛选 ────────────────────────
    bet_recommendation = None
    if market_probs:
        # 市场大2.5隐含概率: 优先用联赛画像的历史大球率
        # (Kambi API的totals市场也可以拉, 但目前只拉了1X2)
        market_over25_est = profile.over_25_rate  # 联赛历史大球率
        bet_recommendation = recommend_bets(
            home_team=home_name,
            away_team=away_name,
            model_home=final_home,
            model_draw=final_draw,
            model_away=final_away,
            market_home=market_probs["home"],
            market_draw=market_probs["draw"],
            market_away=market_probs["away"],
            model_over25=over_25,
            market_over25=market_over25_est,
            model_btts=dc_result["btts"],
            market_btts=profile.btts_rate,
        )

    # ── Step 9: 组装最终结果 ──────────────────────────
    return {
        "match": f"{home_name} vs {away_name}",
        "league": profile.name,
        "league_code": league_code,
        "kickoff": match.get("date", ""),

        # 市场信号
        "kambi_odds": odds_1x2,
        "shin_probs": {
            "home": shin_result.home if shin_result else None,
            "draw": shin_result.draw if shin_result else None,
            "away": shin_result.away if shin_result else None,
            "margin": shin_result.margin if shin_result else None,
        } if shin_result else None,

        # ELO
        "home_elo": home_st["elo"],
        "away_elo": away_st["elo"],
        "elo_diff": round(home_st["elo"] - away_st["elo"], 1),
        "home_elo_source": home_st["source"],
        "away_elo_source": away_st["source"],

        # 五基报告 (精简)
        "five_bases": {
            "bases": [
                {
                    "name": b.base_name,
                    "home_win": round(b.distribution.home_win, 4),
                    "draw": round(b.distribution.draw, 4),
                    "away_win": round(b.distribution.away_win, 4),
                    "top1_score": b.distribution.top1_score,
                    "concentration": round(b.distribution.concentration_index, 4),
                }
                for b in five_base_report.bases
            ],
            "collapse_warning": five_base_report.collapse_warning,
            "collapse_detail": five_base_report.collapse_detail,
            "agreement_matrix": five_base_report.agreement_matrix,
        },

        # 六维预测
        "prediction": {
            "dim1_1x2": {
                "home_win": final_home,
                "draw": final_draw,
                "away_win": final_away,
                "direction": "主胜" if final_home >= final_away else
                            ("客胜" if final_away > final_home else "平局倾向"),
                "confidence": "高" if max(final_home, final_draw, final_away) > 0.55 else
                             ("中" if max(final_home, final_draw, final_away) > 0.45 else "低"),
            },
            "dim2_correct_score": [
                {"score": s, "prob": round(p, 4)} for s, p in top_scores
            ],
            "dim3_total_goals": {
                "over_25": round(over_25, 4),
                "over_35": round(over_35, 4),
                "expected_total": round(lam_h + lam_a, 2),
                "recommendation": "大2.5" if over_25 > 0.50 else "小2.5",
            },
            "dim4_half_time": {
                "over_15_prob": round(half_over_15, 4),
                "recommendation": "半场大1.5" if half_over_15 > 0.50 else "半场小1.5",
            },
            "dim5_half_handicap": {
                "home_win": round(half_hw, 4),
                "draw": round(1 - half_hw - half_aw, 4),
                "away_win": round(half_aw, 4),
            },
            "dim6_corners": {
                "expected_total": round(expected_corners, 1),
                "home_share": round(corner_home_share, 4),
                "recommendation": f"角球大{expected_corners - 0.5:.1f}" if expected_corners > 9.5
                                 else f"角球小{expected_corners + 0.5:.1f}",
            },
        },

        # Dixon-Coles 诊断
        "dixon_coles": {
            "rho": dc_rho,
            "diagnostics": dc_result["diagnostics"],
            "concentration": dc_result["concentration"],
        },

        # 基线对比
        "baseline": {
            "home_win": baseline.home_win,
            "draw": baseline.draw,
            "away_win": baseline.away_win,
            "expected_goals": baseline.expected_total_goals,
            "source": baseline.source,
        },

        # 深盘检查
        "handicap_check": handicap_check,

        # 投注推荐
        "bet_recommendation": bet_recommendation,

        # 决策链
        "decision_chain": _build_decision_chain(
            home_name, away_name, profile,
            home_st, away_st, five_base_report,
            handicap_check, bet_recommendation,
            dc_result, final_home, final_draw, final_away,
            market_probs,
        ),

        # 冷启动标记
        "cold_start": home_st["is_cold"] or away_st["is_cold"],
    }


def _build_decision_chain(home: str, away: str, profile: LeagueProfile,
                          home_st: dict, away_st: dict,
                          five_base_report: Any,
                          handicap_check: dict,
                          bet_rec: dict | None,
                          dc_result: dict,
                          fh: float, fd: float, fa: float,
                          market_probs: dict | None) -> list[str]:
    """构建可读的决策逻辑链"""
    chain = []

    # 1. 联赛画像
    chain.append(
        f"① 联赛画像: {profile.name} | "
        f"场均{profile.avg_total_goals}球 | "
        f"主胜{profile.home_win_rate:.0%}/平{profile.draw_rate:.0%}/客胜{profile.away_win_rate:.0%} | "
        f"大2.5率{profile.over_25_rate:.0%}"
    )

    # 2. ELO
    chain.append(
        f"② ELO: {home} {home_st['elo']:.0f} ({home_st['source']}) | "
        f"{away} {away_st['elo']:.0f} ({away_st['source']}) | "
        f"差={home_st['elo'] - away_st['elo']:+.0f}"
    )

    # 3. 市场信号
    if market_probs:
        chain.append(
            f"③ 市场(Shin去水): H={market_probs['home']:.1%} "
            f"D={market_probs['draw']:.1%} A={market_probs['away']:.1%} | "
            f"margin={market_probs['margin']:.1%}"
        )
    else:
        chain.append("③ 市场: 无Kambi赔率")

    # 4. 五基共识
    n_bases = len(five_base_report.bases)
    agree_count = sum(1 for v in five_base_report.agreement_matrix.values() if v)
    total_pairs = len(five_base_report.agreement_matrix)
    chain.append(
        f"④ 五基共识: {agree_count}/{total_pairs}对一致 | "
        f"塌陷警告={'⚠️ '+five_base_report.collapse_detail if five_base_report.collapse_warning else '✅ 无'}"
    )

    # 5. DC修正
    d11 = dc_result["diagnostics"]["1-1_prob"]
    d00 = dc_result["diagnostics"]["0-0_prob"]
    chain.append(
        f"⑤ DC修正(ρ={dc_result['rho']}): 1-1={d11:.1%} 0-0={d00:.1%} | "
        f"集中度={dc_result['concentration']:.3f}"
    )

    # 6. 深盘
    if handicap_check["is_deep"]:
        chain.append(
            f"⑥ 深盘检查: {'🔴' if handicap_check['warning_level']=='danger' else '🟡'} "
            f"{handicap_check['recommendation']}"
        )
    else:
        chain.append("⑥ 深盘检查: ✅ 非深盘")

    # 7. 最终方向
    direction = "主胜" if fh >= fa else ("客胜" if fa > fh else "平局倾向")
    chain.append(f"⑦ 最终: {direction} H={fh:.1%} D={fd:.1%} A={fa:.1%}")

    # 8. 投注建议
    if bet_rec and bet_rec.get("best_bet"):
        bb = bet_rec["best_bet"]
        chain.append(f"⑧ 投注: {bb['pick']} | edge={bb['edge']:+.1%} | 置信={bb['confidence']}")
    else:
        chain.append("⑧ 投注: 无符合阈值 (edge<5%或概率不达标)")

    return chain


# ══════════════════════════════════════════════════════════════
# 阶段入口
# ══════════════════════════════════════════════════════════════

def phase_morning(date_str: str | None = None):
    """早盘: 拉取Kambi赔率 + 初筛"""
    logger.info("═══ 早盘分析 ═══")
    _load_or_fetch_kambi(date_str)
    # 初筛: 简单的ELO+赔率对比
    matches = _load_kambi_matches()
    logger.info(f"早盘共 {len(matches)} 场待分析")


def phase_afternoon(date_str: str | None = None):
    """午盘: 蒸汽移动检测 + 赔率更新"""
    logger.info("═══ 午盘分析 ═══")
    _load_or_fetch_kambi(date_str)
    # TODO: 对比 morning 基准检测蒸汽移动
    matches = _load_kambi_matches()
    logger.info(f"午盘共 {len(matches)} 场待分析")


def phase_final(date_str: str | None = None, output_html: bool = True):
    """终盘: 完整管线 → 六维预测 → HTML"""
    logger.info("═══ 终盘预测 ═══")
    logger.info("管线: Kambi→Shin→ELO→五基→DC→基线→best_bets→深盘→六维")

    _load_or_fetch_kambi(date_str)
    matches = _load_kambi_matches()

    if not matches:
        logger.error("无比赛数据! 请先运行 python fetch_kambi.py")
        return

    logger.info(f"共 {len(matches)} 场, 开始完整预测...")

    cold_engine = ColdStartEngine()

    results = []
    for i, match in enumerate(matches):
        logger.info(f"[{i+1}/{len(matches)}]")
        try:
            result = predict_one_match(match, cold_engine)
            results.append(result)
        except Exception as e:
            logger.error(f"  预测失败: {e}")
            import traceback
            traceback.print_exc()

    # 统计
    with_odds = sum(1 for r in results if r.get("shin_probs"))
    with_bet = sum(1 for r in results
                   if r.get("bet_recommendation") and r["bet_recommendation"].get("best_bet"))
    cold_count = sum(1 for r in results if r.get("cold_start"))
    deep_warnings = sum(1 for r in results
                        if r.get("handicap_check", {}).get("warning_level") != "none")

    logger.info(
        f"═══ 终盘统计: {len(results)}场 | "
        f"有赔率{with_odds} | 推荐投注{with_bet} | 冷启动{cold_count} | 深盘警告{deep_warnings} ═══"
    )

    # 保存 JSON
    output_dir = ROOT / "data"
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / f"pipeline_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    logger.info(f"JSON结果: {json_path}")

    # 生成 HTML
    if output_html:
        html_path = _generate_html(results, date_str)
        logger.info(f"HTML报告: {html_path}")

    return results


# ══════════════════════════════════════════════════════════════
# 辅助: Kambi数据加载
# ══════════════════════════════════════════════════════════════

def _load_or_fetch_kambi(date_str: str | None = None):
    """加载本地Kambi JSON, 如果没有则直接拉取API (不过滤联赛)"""
    json_path = ROOT / "data" / "kambi_odds.json"
    if json_path.exists():
        mtime = datetime.fromtimestamp(json_path.stat().st_mtime)
        age_min = (datetime.now() - mtime).total_seconds() / 60
        if age_min < 60:
            logger.info(f"Kambi数据 {age_min:.0f}分钟前, 复用")
            return

    logger.info("直接拉取Kambi API (全联赛, 不限制欧战)...")
    _fetch_all_kambi(json_path)


def _fetch_all_kambi(json_path: Path):
    """拉取今日所有足球赛事的Kambi赔率 (不限联赛)

    与 fetch_kambi.py 的区别: fetch_kambi.py 只拉欧战资格赛。
    管线需要覆盖所有联赛, 所以这里不过滤联赛名。
    """
    import requests
    env_path = ROOT / ".env"
    KEY = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ODDS_API_IO_KEY="):
                KEY = line.split("=", 1)[1].strip()
                break

    if not KEY:
        logger.error("未找到 ODDS_API_IO_KEY, 无法拉取赔率")
        return

    BOOKMAKER = "Unibet"

    # Step 1: 拉取所有足球赛事
    logger.info("  Step 1: 拉取赛事列表...")
    r = requests.get("https://api.odds-api.io/v3/events", params={
        "sport": "football", "bookmaker": BOOKMAKER, "apiKey": KEY,
    }, timeout=30)
    events = r.json() if not isinstance(r, str) else json.loads(r.text)
    if isinstance(events, str):
        events = json.loads(events)
    if isinstance(events, dict) and "data" in events:
        events = events["data"]  # 某些API包装在data字段
    if not isinstance(events, list):
        logger.error(f"API返回格式异常: {type(events)} -> {str(events)[:200]}")
        return
    pending = [e for e in events if e.get("status") in ("pending", "live")]
    logger.info(f"  {len(pending)} 场待踢 / 共 {len(events)} 场")

    # 只处理重点联赛 (有 league_profiles 的联赛 → 联赛名能映射成功的)
    top_leagues = []
    for e in pending:
        league_name = e.get("league", {}).get("name", "")
        code = map_league(league_name)
        if code != "DEFAULT":
            top_leagues.append(e)

    # 也保留一些没映射但有赔率的重要联赛
    other = [e for e in pending if e not in top_leagues]
    # 最多处理100场 (API限速)
    matches_to_process = (top_leagues + other)[:100]
    logger.info(f"  重点联赛 {len(top_leagues)} 场, 总计处理 {len(matches_to_process)} 场")

    # Step 2: 批量拉取赔率
    logger.info("  Step 2: 拉取赔率...")
    for i, m in enumerate(matches_to_process):
        try:
            time.sleep(0.15)  # API限速
            r2 = requests.get("https://api.odds-api.io/v3/odds", params={
                "eventId": m["id"], "bookmakers": BOOKMAKER, "apiKey": KEY,
            }, timeout=15)
            data = r2.json()

            bms = data.get("bookmakers", {})
            if isinstance(bms, dict):
                for bm_name, markets in bms.items():
                    if isinstance(markets, list):
                        for mkt in markets:
                            if mkt.get("name") in ("ML", "1X2", "Full Time Result"):
                                odds_list = mkt.get("odds", [])
                                if odds_list:
                                    o = odds_list[0]
                                    m["odds_1x2"] = {
                                        "home": float(o.get("home", 0)),
                                        "draw": float(o.get("draw", 0)),
                                        "away": float(o.get("away", 0)),
                                    }
                                    m["odds_source"] = f"{BOOKMAKER} (Kambi)"
                                    break
            if (i + 1) % 20 == 0:
                logger.info(f"    {i+1}/{len(matches_to_process)}...")
        except Exception as e:
            logger.debug(f"    {m.get('home','')[:20]}: {e}")

    with_odds = sum(1 for m in matches_to_process if m.get("odds_1x2"))
    logger.info(f"  已保存 {len(matches_to_process)} 场 ({with_odds} 有Unibet赔率)")

    json_path.write_text(
        json.dumps(matches_to_process, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_kambi_matches() -> list[dict]:
    """加载Kambi赔率JSON, 返回待踢比赛"""
    json_path = ROOT / "data" / "kambi_odds.json"
    if not json_path.exists():
        logger.error(f"未找到 {json_path}")
        return []
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return [m for m in data if m.get("status") not in ("FT", "finished", "FINISHED", "settled")]


# ══════════════════════════════════════════════════════════════
# HTML 生成
# ══════════════════════════════════════════════════════════════

def _generate_html(results: list[dict], date_str: str | None = None) -> Path:
    """从管线结果生成终盘预测HTML"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    rows_html = ""
    for r in results:
        p = r["prediction"]
        d1 = p["dim1_1x2"]
        d2 = p["dim2_correct_score"]
        d3 = p["dim3_total_goals"]
        d4 = p["dim4_half_time"]
        d5 = p["dim5_half_handicap"]
        d6 = p["dim6_corners"]
        hc = r.get("handicap_check", {})
        bet = r.get("bet_recommendation", {})
        chain = r.get("decision_chain", [])

        # 置信度标签
        conf = d1["confidence"]
        conf_cls = "g" if conf == "高" else ("y" if conf == "中" else "r")

        # 投注标签
        bet_html = ""
        if bet and bet.get("best_bet"):
            bb = bet["best_bet"]
            bet_html = f'<span class="tag tp">投注: {bb["pick"]} (edge={bb["edge"]:+.1%})</span>'
        elif hc.get("warning_level") == "danger":
            bet_html = '<span class="tag tr">禁止</span>'
        elif r.get("cold_start"):
            bet_html = '<span class="tag ts">参考(冷启动)</span>'
        else:
            bet_html = '<span class="tag tb">参考</span>'

        # 深盘警告
        hc_html = ""
        if hc.get("warning_level") != "none":
            hc_html = (f'<span class="tag tr">⚠ {hc["recommendation"][:40]}</span>'
                       if hc["warning_level"] == "danger"
                       else f'<span class="tag ts">⚠ {hc["recommendation"][:40]}</span>')

        # 比分
        scores_html = " ".join(
            f'<span style="color:var(--accent)">{s["score"]}</span> <small>{s["prob"]:.1%}</small>'
            for s in d2[:3]
        )

        # 决策链(折叠)
        chain_html = "<br>".join(chain)

        rows_html += f"""
        <tr>
          <td class="l"><b>{r['match']}</b><br><small>{r['league']} · {r['kickoff'][:16] if r['kickoff'] else ''}</small></td>
          <td class="{conf_cls}">{d1['direction']}<br><small>H:{d1['home_win']:.1%} D:{d1['draw']:.1%} A:{d1['away_win']:.1%}</small></td>
          <td>{scores_html}</td>
          <td class="{('g' if d3['recommendation'].startswith('大') else 'r')}">{d3['recommendation']}<br><small>O2.5={d3['over_25']:.1%} · E[总]={d3['expected_total']}</small></td>
          <td class="{('g' if d4['recommendation'].startswith('半场大') else 'r')}">{d4['recommendation']}<br><small>O1.5={d4['over_15_prob']:.1%}</small></td>
          <td>{'主' if d5['home_win'] > 0.4 else ('客' if d5['away_win'] > 0.4 else '均')}<br><small>H:{d5['home_win']:.1%} A:{d5['away_win']:.1%}</small></td>
          <td>{d6['recommendation']}<br><small>E[{d6['expected_total']}] · 主占{d6['home_share']:.0%}</small></td>
          <td>{bet_html} {hc_html}</td>
          <td class="l" style="font-size:0.65em;max-width:300px">{chain_html}</td>
        </tr>"""

    # 统计摘要
    with_bet = sum(1 for r in results
                   if r.get("bet_recommendation") and r["bet_recommendation"].get("best_bet"))
    cold_count = sum(1 for r in results if r.get("cold_start"))
    deep_warnings = sum(1 for r in results
                        if r.get("handicap_check", {}).get("warning_level") != "none")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘预测 · {date_str}</title>
<style>
:root{{--bg:#09090d;--card:#111118;--border:#1c1c2a;--text:#c8c8d4;--muted:#5a5a6e;
  --accent:#f0a838;--green:#3fb950;--red:#f85149;--blue:#58a6ff;--cyan:#00d4ff;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);font-size:13px;line-height:1.6}}
.w{{max-width:100%;margin:0 auto;padding:16px;min-width:1024px}}
h1{{font-size:1.1em;margin-bottom:4px}}h1 em{{color:var(--accent);font-style:normal}}
.sub{{font-size:0.62em;color:var(--muted);margin-bottom:12px}}
.summary{{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}}
.si{{flex:1;min-width:70px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}}
.si .n{{font-size:1.2em;font-weight:800}}.si .l{{font-size:0.55em;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:0.78em}}
th{{background:#14141e;padding:7px 5px;text-align:center;font-weight:600;color:var(--muted);font-size:0.75em;border-bottom:2px solid var(--border);position:sticky;top:0;z-index:1}}
td{{padding:6px 5px;text-align:center;border-bottom:1px solid var(--border);vertical-align:top}}
td.l{{text-align:left}}.g{{color:var(--green);font-weight:700}}.r{{color:var(--red)}}.y{{color:var(--accent)}}
.tag{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:0.6em;font-weight:600}}
.tp{{background:rgba(63,185,80,0.1);color:var(--green)}}
.tr{{background:rgba(248,81,73,0.1);color:var(--red)}}
.tb{{background:rgba(88,166,255,0.1);color:var(--blue)}}
.ts{{background:rgba(240,168,56,0.1);color:var(--accent)}}
small{{color:var(--muted);font-size:0.85em}}
tr:hover{{background:rgba(255,255,255,0.01)}}
.ft{{text-align:center;padding:18px;color:var(--muted);font-size:0.55em;opacity:0.35}}
.note{{background:rgba(240,168,56,0.05);border:1px solid rgba(240,168,56,0.15);padding:8px 14px;border-radius:6px;margin-bottom:10px;font-size:0.72em}}
</style>
</head>
<body>
<div class="w">
<h1>⚽ 终盘预测 <em>{date_str}</em></h1>
<p class="sub">管线: Kambi→Shin→ELO→五基→DC→基线→best_bets→深盘→六维 · 生成于 {now.strftime('%H:%M')}</p>

<div class="summary">
  <div class="si"><div class="n">{len(results)}</div><div class="l">比赛</div></div>
  <div class="si"><div class="n" style="color:var(--green)">{with_bet}</div><div class="l">推荐投注</div></div>
  <div class="si"><div class="n" style="color:var(--blue)">{cold_count}</div><div class="l">冷启动</div></div>
  <div class="si"><div class="n" style="color:var(--red)">{deep_warnings}</div><div class="l">深盘警告</div></div>
</div>

<div class="note">
  🔬 <b>本次预测启用的模块:</b>
  ✅ Kambi实时赔率(Unibet) ✅ Shin去水 ✅ ELO评分 ✅ 五基并行(B0/B1+/B2-RC/P_CANDIDATE/Xalpha)
  ✅ Dixon-Coles ρ修正 ✅ 联赛基线对比 ✅ best_bets阈值筛选 ✅ 深盘规则检查 ✅ 冷启动引擎
</div>

<table>
<tr>
  <th>① 比赛</th><th>② 胜平负</th><th>③ 波胆</th><th>④ 全场大小</th><th>⑤ 半场大小</th><th>⑥ 半场让球</th><th>⑦ 角球</th><th>推荐</th><th>决策逻辑链</th>
</tr>
{rows_html}
</table>

<div class="ft">© JOYBOY · 管线自动生成 · 禁止盲目跟单</div>
</div>
</body>
</html>"""

    output_path = ROOT / "today_final.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ══════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="足球预测主管线 · 一条命令跑通全部模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py --phase morning      # 早盘: 拉赔率+初筛
  python run_pipeline.py --phase afternoon    # 午盘: 蒸汽检测+更新
  python run_pipeline.py --phase final        # 终盘: 完整管线→HTML
  python run_pipeline.py --phase final --no-html  # 终盘: 只出JSON
        """,
    )
    parser.add_argument("--phase", choices=["morning", "afternoon", "final"],
                        default="final", help="分析阶段")
    parser.add_argument("--date", help="日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--no-html", action="store_true", help="不生成HTML")
    parser.add_argument("--rho", type=float, default=-0.10,
                        help="Dixon-Coles ρ参数 (默认-0.10)")
    args = parser.parse_args()

    logger.info(f"JOYBOY 足球预测管线 v1.0")
    logger.info(f"阶段: {args.phase} | 日期: {args.date or '今天'} | DC ρ={args.rho}")

    if args.phase == "morning":
        phase_morning(args.date)
    elif args.phase == "afternoon":
        phase_afternoon(args.date)
    elif args.phase == "final":
        phase_final(args.date, output_html=not args.no_html)

    logger.info("✅ 管线完成")


if __name__ == "__main__":
    main()
