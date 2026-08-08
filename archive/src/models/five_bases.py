"""
五底座并行预测体系

核心原则:
  1. 同一场比赛、同一证据、同一冻结时刻 → 5种不同逻辑独立输出
  2. 非多数表决 —— 保留分歧, 不夸大共识
  3. 连续赛前样本足够前, 不提前确定领先者或淘汰顺序
  4. 诊断1-1结构塌陷: 降排名不是成功标准, 需统一口径判断整体改善

五底座:
  B0          固定泊松分区基础矩阵 (无先验, 无市场)
  B1+         历史分层先验 + 市场软约束
  B2-RC       按胜/平/负 重建进球分布
  P_CANDIDATE 自适应融合 + 集中保护
  Xalpha      公平市场信号 + 独立结构偏移
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 共享数据结构
# ============================================================

@dataclass
class ScoreDistribution:
    """完整比分分布"""
    scores: dict[str, float]       # {"0-0": 0.08, "1-0": 0.12, ...}
    total_mass: float = 1.0        # 概率总质量 (应≈1.0)

    # 胜平负边际
    home_win: float = 0.0
    draw: float = 0.0
    away_win: float = 0.0

    # 集中度诊断
    top1_score: str = ""           # 最高概率比分
    top1_prob: float = 0.0
    top3_scores: list[str] = field(default_factory=list)
    concentration_index: float = 0.0  # Herfindahl指数 (>0.15=过度集中)


@dataclass
class BaseOutput:
    """单个底座的输出"""
    base_name: str                 # "B0" / "B1+" / "B2-RC" / "P_CANDIDATE" / "Xalpha"
    distribution: ScoreDistribution = field(default_factory=ScoreDistribution)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FiveBaseReport:
    """五底座并行报告"""
    match_label: str = ""
    bases: list[BaseOutput] = field(default_factory=list)

    # 结构塌陷诊断
    collapse_warning: bool = False
    collapse_detail: str = ""

    # 底座间一致性
    agreement_matrix: dict[str, float] = field(default_factory=dict)


# ============================================================
# 泊松核心 (所有底座共用)
# ============================================================

def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _score_matrix(lam_h: float, lam_a: float, max_g: int = 8) -> dict[str, float]:
    """生成完整比分矩阵"""
    dist: dict[str, float] = {}
    total = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = _poisson_pmf(h, lam_h) * _poisson_pmf(a, lam_a)
            dist[f"{h}-{a}"] = p
            total += p
    # 归一化
    for k in dist:
        dist[k] /= total
    return dist


def _marginals(dist: dict[str, float]) -> tuple[float, float, float]:
    """从比分分布计算胜平负边际概率"""
    hw = dr = aw = 0.0
    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a: hw += prob
        elif h == a: dr += prob
        else: aw += prob
    return hw, dr, aw


def _concentration(dist: dict[str, float]) -> float:
    """Herfindahl 集中度指数: Σp_i². >0.15 = 过度集中"""
    return sum(p * p for p in dist.values())


def _diagnose_collapse(dist: ScoreDistribution) -> tuple[bool, str]:
    """诊断 1-1 结构塌陷"""
    has_11 = dist.scores.get("1-1", 0)
    issues = []

    if has_11 > 0.20:
        issues.append(f"1-1 概率 {has_11:.0%} 异常高 (>20%)")
    if dist.top1_score == "1-1" and dist.top1_prob > 0.15:
        issues.append(f"1-1 排第一且概率 {dist.top1_prob:.0%}")

    # 检查 Top3 中是否有反常集中
    top3 = sorted(dist.scores.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_mass = sum(p for _, p in top3)
    if top3_mass > 0.55:
        issues.append(f"Top3比分集中度过高 ({top3_mass:.0%})")

    return len(issues) > 0, "; ".join(issues)


# ============================================================
# B0: 固定泊松分区基础矩阵
# ============================================================

def b0_fixed_poisson(
    home_attack: float, home_defense: float,
    away_attack: float, away_defense: float,
    home_advantage: float = 0.25,
    league_avg: float = 2.70,
) -> BaseOutput:
    """B0: 最简模型 —— 无先验, 无市场, 纯泊松

    这是整个体系的锚点。比B0更简单的只有"闭眼猜均值"。
    B0不依赖任何外部数据源(无ELO, 无赔率), 只接受攻防力参数。
    """
    base = league_avg / 2
    lam_h = base * home_attack * away_defense * (1 + home_advantage)
    lam_a = base * away_attack * home_defense
    lam_h = max(0.1, min(6.0, lam_h))
    lam_a = max(0.1, min(6.0, lam_a))

    dist = _score_matrix(lam_h, lam_a)
    hw, dr, aw = _marginals(dist)
    top = sorted(dist.items(), key=lambda x: x[1], reverse=True)

    sd = ScoreDistribution(
        scores=dist, home_win=hw, draw=dr, away_win=aw,
        top1_score=top[0][0], top1_prob=top[0][1],
        top3_scores=[s for s, _ in top[:3]],
        concentration_index=_concentration(dist),
    )
    collapse, detail = _diagnose_collapse(sd)

    return BaseOutput(
        base_name="B0",
        distribution=sd,
        metadata={
            "lambda_home": round(lam_h, 3), "lambda_away": round(lam_a, 3),
            "collapse_warning": collapse, "collapse_detail": detail,
            "method": "纯泊松, 无先验, 无市场, 无ELO",
        },
    )


# ============================================================
# B1+: 历史分层先验 + 市场软约束
# ============================================================

def b1_plus_historical_prior(
    home_attack: float, home_defense: float,
    away_attack: float, away_defense: float,
    league_home_win_rate: float = 0.40,
    league_draw_rate: float = 0.28,
    market_home_prob: float | None = None,
    market_draw_prob: float | None = None,
    market_away_prob: float | None = None,
    home_advantage: float = 0.25,
    league_avg: float = 2.70,
) -> BaseOutput:
    """B1+: 联赛画像作为 Dirichlet 先验, 市场赔率(可选)作为软约束

    与B0的核心区别:
      - 引入联赛画像先验 (主场胜率, 平局率, 客场胜率)
      - 如果提供市场概率, 作为似然约束比分分布
      - 保持泊松形状但调整边际以匹配先验
    """
    base = league_avg / 2
    lam_h = base * home_attack * away_defense * (1 + home_advantage)
    lam_a = base * away_attack * home_defense
    lam_h = max(0.1, min(6.0, lam_h))
    lam_a = max(0.1, min(6.0, lam_a))

    dist = _score_matrix(lam_h, lam_a)
    hw_raw, dr_raw, aw_raw = _marginals(dist)

    # Dirichlet 先验 → 调整边际
    prior_h, prior_d, prior_a = league_home_win_rate, league_draw_rate, 1 - league_home_win_rate - league_draw_rate
    alpha = 0.30  # 先验权重 (30% 先验 + 70% 泊松原始)
    hw_adj = hw_raw * (1 - alpha) + prior_h * alpha
    dr_adj = dr_raw * (1 - alpha) + prior_d * alpha
    aw_adj = aw_raw * (1 - alpha) + prior_a * alpha

    # 如果提供市场概率, 再做第二次融合
    if market_home_prob is not None:
        beta = 0.25  # 市场权重
        hw_adj = hw_adj * (1 - beta) + market_home_prob * beta
        dr_adj = dr_adj * (1 - beta) + market_draw_prob * beta
        aw_adj = aw_adj * (1 - beta) + market_away_prob * beta

    # 归一化
    total = hw_adj + dr_adj + aw_adj
    hw_adj /= total; dr_adj /= total; aw_adj /= total

    # 按调整后的边际重新缩放比分分布
    adj_dist: dict[str, float] = {}
    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a:
            adj_dist[score] = prob * (hw_adj / hw_raw) if hw_raw > 0 else prob
        elif h == a:
            adj_dist[score] = prob * (dr_adj / dr_raw) if dr_raw > 0 else prob
        else:
            adj_dist[score] = prob * (aw_adj / aw_raw) if aw_raw > 0 else prob

    # 归一化
    total_p = sum(adj_dist.values())
    for k in adj_dist:
        adj_dist[k] /= total_p

    top = sorted(adj_dist.items(), key=lambda x: x[1], reverse=True)
    sd = ScoreDistribution(
        scores=adj_dist, home_win=hw_adj, draw=dr_adj, away_win=aw_adj,
        top1_score=top[0][0], top1_prob=top[0][1],
        top3_scores=[s for s, _ in top[:3]],
        concentration_index=_concentration(adj_dist),
    )
    collapse, detail = _diagnose_collapse(sd)

    return BaseOutput(
        base_name="B1+",
        distribution=sd,
        metadata={
            "prior_weights": {"league": alpha, "market": beta if market_home_prob else 0},
            "collapse_warning": collapse, "collapse_detail": detail,
            "method": "Dirichlet先验(联赛画像) + 市场软约束(可选)",
        },
    )


# ============================================================
# B2-RC: 按胜/平/负 重建进球分布
# ============================================================

def b2_result_conditioned(
    home_attack: float, home_defense: float,
    away_attack: float, away_defense: float,
    home_advantage: float = 0.25,
    league_avg: float = 2.70,
) -> BaseOutput:
    """B2-RC: 分割后重建 —— 分别计算 P(score | H), P(score | D), P(score | A)

    核心思想:
      先算胜平负边际概率, 然后在每种结果类型内部独立计算比分分布。
      这天然防止了 1-1 跨结果类型污染 —— 1-1 只出现在平局分布中,
      不会同时出现在主胜和客胜的比分里。

    关键优势:
      1-1 只能从平局概率(通常20-28%)中分得份额, 不会挤占其他结果的空间。
    """
    base = league_avg / 2
    lam_h = base * home_attack * away_defense * (1 + home_advantage)
    lam_a = base * away_attack * home_defense
    lam_h = max(0.1, min(6.0, lam_h))
    lam_a = max(0.1, min(6.0, lam_a))

    # Step 1: 计算原始比分矩阵
    raw_dist = _score_matrix(lam_h, lam_a)

    # Step 2: 按结果类型分组
    h_scores: dict[str, float] = {}  # 主胜比分
    d_scores: dict[str, float] = {}  # 平局比分
    a_scores: dict[str, float] = {}  # 客胜比分

    for score, prob in raw_dist.items():
        h, a = map(int, score.split("-"))
        if h > a:
            h_scores[score] = prob
        elif h == a:
            d_scores[score] = prob
        else:
            a_scores[score] = prob

    # Step 3: 各类型内部归一化
    h_total = sum(h_scores.values())
    d_total = sum(d_scores.values())
    a_total = sum(a_scores.values())

    hw = h_total / (h_total + d_total + a_total)
    dr = d_total / (h_total + d_total + a_total)
    aw = a_total / (h_total + d_total + a_total)

    # Step 4: 对平局分布施加形状约束
    # 防止 1-1 在平局内过度集中 (>40%的平局概率不能都给1-1)
    if d_total > 0:
        d_concentration = sum((p / d_total) ** 2 for p in d_scores.values())
        if d_concentration > 0.30:  # 1-1 过度集中
            # 施加 Dirichlet 平滑 → 向均匀分布拉
            n_scores = len(d_scores)
            smoothing = 0.5 / n_scores
            for k in d_scores:
                d_scores[k] = (d_scores[k] + smoothing) / (1 + n_scores * smoothing) * d_total

    # Step 5: 合并
    final_dist: dict[str, float] = {}
    for k, v in h_scores.items(): final_dist[k] = v
    for k, v in d_scores.items(): final_dist[k] = v
    for k, v in a_scores.items(): final_dist[k] = v

    top = sorted(final_dist.items(), key=lambda x: x[1], reverse=True)
    sd = ScoreDistribution(
        scores=final_dist, home_win=hw, draw=dr, away_win=aw,
        top1_score=top[0][0], top1_prob=top[0][1],
        top3_scores=[s for s, _ in top[:3]],
        concentration_index=_concentration(final_dist),
    )
    collapse, detail = _diagnose_collapse(sd)

    # 额外: 1-1 在平局内的占比
    d11_share = d_scores.get("1-1", 0) / d_total if d_total > 0 else 0

    return BaseOutput(
        base_name="B2-RC",
        distribution=sd,
        metadata={
            "1-1_share_in_draws": round(d11_share, 3),
            "draw_total_mass": round(dr, 3),
            "collapse_warning": collapse, "collapse_detail": detail,
            "method": "按W/D/L重建, 平局内1-1集中度约束",
        },
    )


# ============================================================
# P_CANDIDATE: 自适应融合 + 集中保护
# ============================================================

def p_candidate_adaptive(
    b0_output: BaseOutput,
    b1_output: BaseOutput,
    b2_output: BaseOutput,
    concentration_threshold: float = 0.15,
) -> BaseOutput:
    """P_CANDIDATE: 自适应融合三个底座

    核心:
      不是固定权重平均, 而是根据集中度动态调整。
      如果某个底座出现过度集中 (Herfindahl > threshold),
      降低它的权重, 增加更分散的底座的权重。
    """
    bases = [b0_output, b1_output, b2_output]
    concs = [b.distribution.concentration_index for b in bases]

    # 反集中度权重: 越集中 → 权重越低
    inv_concs = [1.0 / max(c, 0.01) for c in concs]
    total_inv = sum(inv_concs)
    weights = [ic / total_inv for ic in inv_concs]

    # 加权融合
    fused: dict[str, float] = {}
    all_scores = set()
    for b in bases:
        all_scores.update(b.distribution.scores.keys())

    for score in all_scores:
        fused[score] = sum(
            weights[i] * bases[i].distribution.scores.get(score, 0)
            for i in range(3)
        )

    # 归一化
    total_p = sum(fused.values())
    for k in fused:
        fused[k] /= total_p

    hw, dr, aw = _marginals(fused)
    top = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    sd = ScoreDistribution(
        scores=fused, home_win=hw, draw=dr, away_win=aw,
        top1_score=top[0][0], top1_prob=top[0][1],
        top3_scores=[s for s, _ in top[:3]],
        concentration_index=_concentration(fused),
    )
    collapse, detail = _diagnose_collapse(sd)

    return BaseOutput(
        base_name="P_CANDIDATE",
        distribution=sd,
        metadata={
            "fusion_weights": {
                "B0": round(weights[0], 3), "B1+": round(weights[1], 3), "B2-RC": round(weights[2], 3),
            },
            "base_concentrations": {"B0": concs[0], "B1+": concs[1], "B2-RC": concs[2]},
            "collapse_warning": collapse, "collapse_detail": detail,
            "method": "反集中度自适应融合, Herfindahl阈值=" + str(concentration_threshold),
        },
    )


# ============================================================
# Xalpha: 公平市场信号 + 独立结构偏移
# ============================================================

def xalpha_market_signal(
    market_home_prob: float,
    market_draw_prob: float,
    market_away_prob: float,
    league_home_win_rate: float = 0.40,
    league_draw_rate: float = 0.28,
    league_avg_goals: float = 2.50,
    home_advantage: float = 0.18,
) -> BaseOutput:
    """Xalpha: 纯市场信号 + 联赛结构偏移

    不使用任何球队特定信息 (无ELO, 无攻防力)。
    只看:
      1. 市场赔率 (Shin去水后) → 胜平负边际
      2. 联赛画像 → 比分形状 (泊松λ基于联赛均值)
      3. 独立结构偏移 → 主场进球加成

    这是"如果只看市场, 不看球队, 能预测多准?"的底座。
    """
    # 用联赛均值构建泊松形状
    base = league_avg_goals / 2
    lam_h = base * (1 + home_advantage)
    lam_a = base

    dist = _score_matrix(lam_h, lam_a)
    hw_raw, dr_raw, aw_raw = _marginals(dist)

    # 将边际替换为市场概率
    adj_dist: dict[str, float] = {}
    for score, prob in dist.items():
        h, a = map(int, score.split("-"))
        if h > a and hw_raw > 0:
            adj_dist[score] = prob * (market_home_prob / hw_raw)
        elif h == a and dr_raw > 0:
            adj_dist[score] = prob * (market_draw_prob / dr_raw)
        else:
            adj_dist[score] = prob * (market_away_prob / aw_raw) if aw_raw > 0 else prob

    total_p = sum(adj_dist.values())
    for k in adj_dist:
        adj_dist[k] /= total_p

    top = sorted(adj_dist.items(), key=lambda x: x[1], reverse=True)
    sd = ScoreDistribution(
        scores=adj_dist,
        home_win=market_home_prob, draw=market_draw_prob, away_win=market_away_prob,
        top1_score=top[0][0], top1_prob=top[0][1],
        top3_scores=[s for s, _ in top[:3]],
        concentration_index=_concentration(adj_dist),
    )
    collapse, detail = _diagnose_collapse(sd)

    return BaseOutput(
        base_name="Xalpha",
        distribution=sd,
        metadata={
            "market_source": "Pinnacle Shin-stripped",
            "collapse_warning": collapse, "collapse_detail": detail,
            "method": "纯市场信号+联赛结构偏移, 无球队ELO",
        },
    )


# ============================================================
# 五底座并行运行器
# ============================================================

def run_five_bases(
    home_team: str, away_team: str,
    league_code: str,
    home_attack: float, home_defense: float,
    away_attack: float, away_defense: float,
    home_advantage: float = 0.18,
    league_avg: float = 2.50,
    market_home_prob: float | None = None,
    market_draw_prob: float | None = None,
    market_away_prob: float | None = None,
) -> FiveBaseReport:
    """运行全部五个底座, 输出并行报告

    Returns:
        FiveBaseReport 包含5个BaseOutput, 结构塌陷诊断, 底座间一致性矩阵
    """
    from src.models.league_profiles import get_profile

    p = get_profile(league_code)

    # B0: 纯泊松
    b0 = b0_fixed_poisson(home_attack, home_defense, away_attack, away_defense,
                          home_advantage, league_avg)

    # B1+: 先验+市场
    b1 = b1_plus_historical_prior(home_attack, home_defense, away_attack, away_defense,
                                  p.home_win_rate, p.draw_rate,
                                  market_home_prob, market_draw_prob, market_away_prob,
                                  home_advantage, league_avg)

    # B2-RC: 按结果重建
    b2 = b2_result_conditioned(home_attack, home_defense, away_attack, away_defense,
                               home_advantage, league_avg)

    # P_CANDIDATE: 自适应融合
    pc = p_candidate_adaptive(b0, b1, b2)

    # Xalpha: 市场信号 (如果有市场数据)
    if market_home_prob is not None:
        xa = xalpha_market_signal(market_home_prob, market_draw_prob or 0.28,
                                  market_away_prob or 0.32, p.home_win_rate,
                                  p.draw_rate, league_avg, home_advantage)
    else:
        # 无市场数据时, Xalpha 退化为联赛均值
        xa = xalpha_market_signal(p.home_win_rate, p.draw_rate, 1 - p.home_win_rate - p.draw_rate,
                                  p.home_win_rate, p.draw_rate, league_avg, home_advantage)

    bases = [b0, b1, b2, pc, xa]

    # 结构塌陷诊断: 任何底座出现 1-1 过度集中?
    any_collapse = any(b.distribution.scores.get("1-1", 0) > 0.20 for b in bases)
    collapse_detail_parts = []
    for b in bases:
        d11 = b.distribution.scores.get("1-1", 0)
        if d11 > 0.15:
            collapse_detail_parts.append(f"{b.base_name}: 1-1={d11:.0%}")
    collapse_detail = "; ".join(collapse_detail_parts) if collapse_detail_parts else "无异常"

    # 底座间一致性: 两两对比方向预测
    names = [b.base_name for b in bases]
    agreement = {}
    for i in range(len(bases)):
        for j in range(i + 1, len(bases)):
            pi = bases[i].distribution
            pj = bases[j].distribution
            # 方向一致 = 两个底座的最大概率方向相同
            same = (
                (pi.home_win >= pi.draw and pi.home_win >= pi.away_win)
                == (pj.home_win >= pj.draw and pj.home_win >= pj.away_win)
            ) and (
                (pi.away_win >= pi.draw and pi.away_win >= pi.home_win)
                == (pj.away_win >= pj.draw and pj.away_win >= pj.home_win)
            )
            agreement[f"{names[i]}-{names[j]}"] = same

    return FiveBaseReport(
        match_label=f"{home_team} vs {away_team}",
        bases=bases,
        collapse_warning=any_collapse,
        collapse_detail=collapse_detail,
        agreement_matrix=agreement,
    )
