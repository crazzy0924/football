"""
蒙特卡洛比分模拟器

基于泊松过程的 10000 次采样，生成:
- 胜平负概率分布
- 比分概率矩阵
- 大小球、双方进球等衍生市场
- 半场/下半场进球分布
- 置信区间

用法:
    result = simulate_match(home_attack=1.2, away_defense=0.9,
                            away_attack=1.0, home_defense=1.1,
                            home_advantage=0.3, n_sims=10000)

设计原则 (来自用户):
    "泊松回归是足球预测的经典基线模型，几乎所有专业模型的内核都是它。
     能输出比分分布，再算胜平负概率、大小球概率、角球等。"
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SimResult:
    """蒙特卡洛模拟结果"""
    home_team: str = ""
    away_team: str = ""
    n_sims: int = 10000

    # 胜平负
    home_win: float = 0.0
    draw: float = 0.0
    away_win: float = 0.0

    # 预期进球 & 置信区间
    home_xg: float = 0.0
    away_xg: float = 0.0
    home_xg_ci: tuple[float, float] = (0, 0)  # 95% CI
    away_xg_ci: tuple[float, float] = (0, 0)

    # 比分分布 (Top 10)
    score_probs: list[dict] = field(default_factory=list)

    # 衍生市场
    over_15: float = 0.0
    over_25: float = 0.0
    over_35: float = 0.0
    over_45: float = 0.0
    btts: float = 0.0           # Both Teams To Score
    home_cs: float = 0.0         # 主队零封
    away_cs: float = 0.0         # 客队零封

    # 半场 (上半场进球≈42%全场)
    h1_over_05: float = 0.0
    h1_over_15: float = 0.0
    h2_over_05: float = 0.0
    h2_over_15: float = 0.0

    # 精确比分 (特定比分查询)
    exact_scores: dict[str, float] = field(default_factory=dict)

    # 进球数分布
    total_goals_dist: list[dict] = field(default_factory=list)


# ============================================================
# 核心: 蒙特卡洛模拟
# ============================================================

async def simulate_match(
    home_team: str = "",
    away_team: str = "",
    home_attack: float = 1.0,
    home_defense: float = 1.0,
    away_attack: float = 1.0,
    away_defense: float = 1.0,
    home_advantage: float = 0.3,
    league_avg_goals: float = 2.70,
    n_sims: int = 10000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """蒙特卡洛泊松模拟

    Args:
        home_team, away_team:   球队名
        home_attack:            主队进攻力 (>1=强于平均, <1=弱)
        home_defense:           主队防守力 (>1=差于平均, <1=好)
        away_attack:            客队进攻力
        away_defense:           客队防守力
        home_advantage:         主场优势 (进球加成, 通常 0.2-0.4)
        league_avg_goals:       联赛场均总进球 (用于校准, 英超≈2.75)
        n_sims:                 模拟次数 (10000=约1秒)
        seed:                   随机种子

    Returns:
        完整模拟结果字典

    算法:
        1. 计算 λ_home = league_avg/2 × home_attack × away_defense × (1 + home_advantage)
        2. 计算 λ_away = league_avg/2 × away_attack × home_defense
        3. n_sims 次泊松采样 → 统计所有结果

    推导 (Dixon-Coles 简化):
        λ_home = baseline × attack_i × defense_j × γ (主场因子)
        其中 baseline = league_avg_goals / 2 (每队均分)
        γ = exp(home_advantage) 或 1 + home_advantage
    """
    if seed is not None:
        np.random.seed(seed)

    # ---- λ 计算 ----
    base = league_avg_goals / 2.0
    gamma = 1.0 + home_advantage  # 主场加成 (e.g. 1.3)

    lam_home = base * home_attack * away_defense * gamma
    lam_away = base * away_attack * home_defense

    # 防止极端值
    lam_home = max(0.1, min(lam_home, 6.0))
    lam_away = max(0.1, min(lam_away, 6.0))

    # ---- 10000 次泊松采样 ----
    home_goals = np.random.poisson(lam_home, n_sims)
    away_goals = np.random.poisson(lam_away, n_sims)

    # ---- 统计 ----
    hw = int(np.sum(home_goals > away_goals))
    dr = int(np.sum(home_goals == away_goals))
    aw = int(np.sum(home_goals < away_goals))

    # 比分频率
    score_counts: dict[tuple[int, int], int] = {}
    for h, a in zip(home_goals, away_goals):
        score_counts[(int(h), int(a))] = score_counts.get((int(h), int(a)), 0) + 1

    # Top 10 比分
    sorted_scores = sorted(score_counts.items(), key=lambda x: x[1], reverse=True)
    top_scores = [
        {"score": f"{h}-{a}", "count": c, "prob": round(c / n_sims, 4)}
        for (h, a), c in sorted_scores[:10]
    ]

    # ---- 衍生市场 ----
    total_goals = home_goals + away_goals
    over_15 = float(np.mean(total_goals > 1.5))
    over_25 = float(np.mean(total_goals > 2.5))
    over_35 = float(np.mean(total_goals > 3.5))
    over_45 = float(np.mean(total_goals > 4.5))
    btts = float(np.mean((home_goals > 0) & (away_goals > 0)))
    home_cs = float(np.mean(away_goals == 0))
    away_cs = float(np.mean(home_goals == 0))

    # ---- 半场 (简化: 上半场~42% 全场 λ) ----
    h1_ratio = 0.42
    lam_h1_home = lam_home * h1_ratio
    lam_h1_away = lam_away * h1_ratio
    lam_h2_home = lam_home * (1 - h1_ratio)
    lam_h2_away = lam_away * (1 - h1_ratio)

    h1_home = np.random.poisson(lam_h1_home, n_sims)
    h1_away = np.random.poisson(lam_h1_away, n_sims)
    h1_total = h1_home + h1_away
    h1_over_05 = float(np.mean(h1_total > 0.5))
    h1_over_15 = float(np.mean(h1_total > 1.5))

    h2_home = np.random.poisson(lam_h2_home, n_sims)
    h2_away = np.random.poisson(lam_h2_away, n_sims)
    h2_total = h2_home + h2_away
    h2_over_05 = float(np.mean(h2_total > 0.5))
    h2_over_15 = float(np.mean(h2_total > 1.5))

    # ---- 精确比分 (常用于 correct score 投注) ----
    exact_scores = {}
    common_scores = [
        "1-0", "2-0", "2-1", "3-0", "3-1", "3-2",
        "0-0", "1-1", "2-2", "0-1", "0-2", "1-2", "0-3", "1-3",
    ]
    for s in common_scores:
        h, a = map(int, s.split("-"))
        exact_scores[s] = round(score_counts.get((h, a), 0) / n_sims, 4)

    # ---- 总进球分布 ----
    tg_counts = {}
    for tg in total_goals:
        tg_counts[int(tg)] = tg_counts.get(int(tg), 0) + 1
    tg_dist = [
        {"goals": g, "prob": round(c / n_sims, 4)}
        for g, c in sorted(tg_counts.items())[:12]
    ]

    # ---- 置信区间 ----
    home_mean = float(np.mean(home_goals))
    away_mean = float(np.mean(away_goals))
    home_std = float(np.std(home_goals))
    away_std = float(np.std(away_goals))
    home_ci = (round(home_mean - 1.96 * home_std / math.sqrt(n_sims), 2),
               round(home_mean + 1.96 * home_std / math.sqrt(n_sims), 2))
    away_ci = (round(away_mean - 1.96 * away_std / math.sqrt(n_sims), 2),
               round(away_mean + 1.96 * away_std / math.sqrt(n_sims), 2))

    return {
        "match": f"{home_team} vs {away_team}" if home_team else "",
        "home_team": home_team,
        "away_team": away_team,
        "model_params": {
            "home_attack": home_attack,
            "home_defense": home_defense,
            "away_attack": away_attack,
            "away_defense": away_defense,
            "home_advantage": home_advantage,
            "lambda_home": round(lam_home, 3),
            "lambda_away": round(lam_away, 3),
            "n_simulations": n_sims,
        },
        "match_result": {
            "home_win": round(hw / n_sims, 4),
            "draw": round(dr / n_sims, 4),
            "away_win": round(aw / n_sims, 4),
            "expected_goals": {
                "home": round(home_mean, 2),
                "away": round(away_mean, 2),
                "total": round(home_mean + away_mean, 2),
            },
            "home_xg_95ci": home_ci,
            "away_xg_95ci": away_ci,
        },
        "score_distribution": top_scores,
        "exact_scores": exact_scores,
        "derived_markets": {
            "over_1_5": round(over_15, 4),
            "over_2_5": round(over_25, 4),
            "over_3_5": round(over_35, 4),
            "over_4_5": round(over_45, 4),
            "both_to_score": round(btts, 4),
            "home_clean_sheet": round(home_cs, 4),
            "away_clean_sheet": round(away_cs, 4),
        },
        "half_markets": {
            "h1_over_0_5": round(h1_over_05, 4),
            "h1_over_1_5": round(h1_over_15, 4),
            "h2_over_0_5": round(h2_over_05, 4),
            "h2_over_1_5": round(h2_over_15, 4),
        },
        "total_goals_distribution": tg_dist,
    }


# ============================================================
# 便捷: 从球队 ELO 估算攻防力
# ============================================================

def elo_to_strength(elo: float) -> dict[str, float]:
    """ELO 评分 → 攻防力指数

    经验映射: ELO 高 → attack↑ defense↓ (好防守)
    """
    s = (elo - 1500) / 400.0
    return {
        "attack": round(1.0 + s * 0.6, 2),
        "defense": round(1.0 - s * 0.5, 2),  # <1 = 好防守
    }


# ============================================================
# 便捷: 批量模拟
# ============================================================

async def batch_simulate(matches: list[dict], n_sims: int = 10000) -> list[dict]:
    """批量蒙特卡洛模拟"""
    results = []
    for m in matches:
        result = await simulate_match(
            home_team=m.get("home", ""),
            away_team=m.get("away", ""),
            home_attack=m.get("home_attack", 1.0),
            home_defense=m.get("home_defense", 1.0),
            away_attack=m.get("away_attack", 1.0),
            away_defense=m.get("away_defense", 1.0),
            home_advantage=m.get("home_advantage", 0.3),
            league_avg_goals=m.get("league_avg_goals", 2.70),
            n_sims=n_sims,
        )
        results.append(result)
    return results
