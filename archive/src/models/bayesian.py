"""
贝叶斯分层融合模型

核心思想: 模型预测和赔率市场是两个独立信息源
  - 模型 (Poisson+ELO): 覆盖球队实力、xG、近期状态
  - 市场 (Pinnacle赔率): 覆盖伤停、内幕、资金流向等模型盲区

贝叶斯更新:
  P(结果 | 模型, 市场) ∝ P(模型 | 结果) × P(市场 | 结果) × P(结果)

实现: Dirichlet-Multinomial 共轭模型
  - 先验 = 模型概率 × 置信度 → 伪计数
  - 证据 = 市场隐含概率 × 市场质量 → 伪计数
  - 后验 = (先验伪计数 + 证据伪计数) / 总数

相比固定权重(6:4)的优势:
  - 模型高置信 + 市场高分歧 → 倾向模型 (模型有独特信息)
  - 模型低置信 + 市场高共识 → 倾向市场 (让市场修正模型)
  - 两者一致 → 大幅增强置信度
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class BayesianUpdate:
    """一次贝叶斯更新的完整记录"""
    # 输入
    prior: list[float]         # 模型先验概率 [ph, pd, pa]
    likelihood: list[float]    # 市场隐含概率 [mh, md, ma]
    prior_strength: int        # 先验伪计数 N
    evidence_strength: int     # 证据伪计数 M

    # 输出
    posterior: list[float]     # 贝叶斯后验概率
    confidence_gain: float     # 后验 vs 先验的置信度提升
    model_weight: float        # 实际模型权重 N/(N+M)
    market_weight: float       # 实际市场权重 M/(N+M)

    # 诊断
    interpretation: str = ""   # 人类可读的解释


# ============================================================
# 核心: 贝叶斯更新
# ============================================================

def bayesian_update(
    model_probs: list[float],
    market_probs: list[float],
    model_confidence: float = 0.5,
    market_margin: float = 0.05,
    market_dispersion: float = 0.04,
) -> BayesianUpdate:
    """贝叶斯融合模型预测和市场赔率

    Dirichlet(alpha) 后验 = Dirichlet(prior_counts + evidence_counts)

    Args:
        model_probs:       模型预测概率 [p_home, p_draw, p_away], 和=1
        market_probs:      市场隐含概率 (margin 剥离后), 和=1
        model_confidence:  模型置信度 0~1 (0.35=低, 0.50=中, 0.70=高)
        market_margin:     市场抽水率 (0.02=极低, 0.05=正常, 0.08=高)
        market_dispersion: 赔率离散度 (0.02=高度一致, 0.06=中等, 0.10=分歧大)

    Returns:
        BayesianUpdate 完整记录

    数学推导:
        设先验 Dir(α₁, α₂, α₃) 其中 αᵢ = model_probs[i] × N
        证据来自多项分布观测, 等效于 Dir(β₁, β₂, β₃) 其中 βᵢ = market_probs[i] × M

        后验 = Dir(α₁+β₁, α₂+β₂, α₃+β₃)
        归一化后: posterior[i] = (αᵢ + βᵢ) / (N + M)

    伪计数 N 的确定:
        N = 10 + model_confidence × 50
        → N ∈ [10, 60]
        → 高置信: 先验权重更大 (60:? ≈ 不可被市场轻易推翻)
        → 低置信: 先验权重较小 (10:? ≈ 市场可大幅修正)

    伪计数 M 的确定:
        基础 M = 5 + (1/market_margin) × 0.2
        → 低 margin (Pinnacle 2%): M ≈ 15
        → 高 margin (7%): M ≈ 8
        再乘以共识因子: (1 - market_dispersion × 5)
        → 高共识: M × 0.9
        → 低共识: M × 0.5
        → M ∈ [4, 20]
    """
    # ---- 先验强度 N ----
    N_raw = 10 + int(model_confidence * 50)
    N = max(8, min(65, N_raw))

    # ---- 证据强度 M ----
    # 低 margin → 赔率更可信 → M 更大
    margin_factor = min(1.0, 0.025 / max(market_margin, 0.01))
    M_base = 5 + int(margin_factor * 18)

    # 高共识 (低 dispersion) → 市场更可信 → M 更大
    consensus_factor = max(0.4, 1.0 - market_dispersion * 6)
    M = max(4, min(22, int(M_base * consensus_factor)))

    # ---- Dirichlet 后验 ----
    total = N + M
    posterior = [
        (model_probs[i] * N + market_probs[i] * M) / total
        for i in range(3)
    ]

    # ---- 置信度提升 ----
    # 后验最高概率 - 先验最高概率 = 学到了多少
    model_max = max(model_probs)
    post_max = max(posterior)
    confidence_gain = post_max - model_max

    # ---- 实际权重 ----
    model_weight = N / total
    market_weight = M / total

    # ---- 解释 ----
    interpretation = _generate_interpretation(
        model_confidence, market_margin, market_dispersion,
        model_weight, market_weight, confidence_gain
    )

    return BayesianUpdate(
        prior=model_probs,
        likelihood=market_probs,
        prior_strength=N,
        evidence_strength=M,
        posterior=[round(p, 4) for p in posterior],
        confidence_gain=round(confidence_gain, 4),
        model_weight=round(model_weight, 3),
        market_weight=round(market_weight, 3),
        interpretation=interpretation,
    )


def _generate_interpretation(
    model_conf: float,
    margin: float,
    dispersion: float,
    mw: float,
    mkw: float,
    gain: float,
) -> str:
    """生成人类可读的贝叶斯更新解释"""
    parts = []

    # 权重分配
    parts.append(f"模型权重 {mw:.0%} / 市场权重 {mkw:.0%}")

    # 为什么这样分配
    reasons = []
    if model_conf > 0.55:
        reasons.append("模型高置信→先验增强")
    elif model_conf < 0.40:
        reasons.append("模型低置信→让市场主导修正")

    if margin < 0.03:
        reasons.append("低抽水率(Pinnacle质量高)→证据可信")
    elif margin > 0.06:
        reasons.append("高抽水率→市场信号打折")

    if dispersion > 0.07:
        reasons.append("赔率分歧大→市场共识弱→减少证据权重")
    elif dispersion < 0.03:
        reasons.append("赔率高度一致→市场共识强→证据增强")

    if reasons:
        parts.append("; ".join(reasons))

    # 效果
    if gain > 0.05:
        parts.append(f"→ 后验置信度显著提升 (+{gain:.0%})")
    elif gain > 0.02:
        parts.append(f"→ 后验置信度轻度提升 (+{gain:.0%})")
    elif gain < -0.03:
        parts.append(f"→ 市场拉低了模型置信度 ({gain:.0%})")
    else:
        parts.append("→ 后验与先验基本一致")

    return " | ".join(parts)


# ============================================================
# 批量贝叶斯预测
# ============================================================

def bayesian_match_prediction(
    home_team: str,
    away_team: str,
    model_probs: list[float],
    model_confidence: float,
    pinnacle_odds: dict[str, float] | None = None,
    odds_dispersion: float = 0.04,
    avg_margin: float = 0.05,
) -> dict[str, Any]:
    """单场比赛的完整贝叶斯预测

    Args:
        home_team, away_team: 球队名
        model_probs:          [ph, pd, pa] 模型预测概率
        model_confidence:     模型置信度
        pinnacle_odds:        {"home": 1.53, "draw": 4.20, "away": 5.61} (可选)
        odds_dispersion:      博彩公司间赔率离散度
        avg_margin:           平均抽水率

    Returns:
        完整贝叶斯分析字典
    """
    # 从赔率计算市场隐含概率
    if pinnacle_odds:
        market_probs, margin = _odds_to_probs(
            pinnacle_odds["home"],
            pinnacle_odds["draw"],
            pinnacle_odds["away"],
        )
    else:
        # 无赔率 → 市场=模型 (等权重)
        market_probs = model_probs[:]
        margin = avg_margin

    # 贝叶斯更新
    update = bayesian_update(
        model_probs, market_probs,
        model_confidence=model_confidence,
        market_margin=margin,
        market_dispersion=odds_dispersion,
    )

    # 确定推荐方向
    post = update.posterior
    if post[0] >= post[2] and post[0] >= post[1]:
        pick, pick_label = "H", "主胜"
    elif post[2] >= post[0] and post[2] >= post[1]:
        pick, pick_label = "A", "客胜"
    else:
        pick, pick_label = "D", "平局"

    # 凯利值 (基于后验概率)
    kelly = _calc_kelly(post, pinnacle_odds, pick) if pinnacle_odds else 0.0

    return {
        "match": f"{home_team} vs {away_team}",
        "model_prior": {
            "home": update.prior[0], "draw": update.prior[1], "away": update.prior[2],
        },
        "market_likelihood": {
            "home": update.likelihood[0], "draw": update.likelihood[1], "away": update.likelihood[2],
        },
        "bayesian_posterior": {
            "home": update.posterior[0], "draw": update.posterior[1], "away": update.posterior[2],
        },
        "weights": {
            "model": update.model_weight, "market": update.market_weight,
            "prior_pseudo_counts": update.prior_strength,
            "evidence_pseudo_counts": update.evidence_strength,
        },
        "prediction": {
            "pick": pick_label,
            "confidence": round(max(update.posterior), 4),
            "confidence_gain": update.confidence_gain,
        },
        "kelly_fraction": round(kelly, 4),
        "interpretation": update.interpretation,
    }


def _odds_to_probs(home_odds: float, draw_odds: float, away_odds: float) -> tuple[list[float], float]:
    """赔率 → 隐含概率 (Shin 方法剥离 margin)"""
    if home_odds <= 1.0 or draw_odds <= 1.0 or away_odds <= 1.0:
        return [1 / 3, 1 / 3, 1 / 3], 0.05

    inv = [1 / home_odds, 1 / draw_odds, 1 / away_odds]
    overround = sum(inv)

    # Proportional 剥离
    probs = [inv[i] / overround for i in range(3)]
    margin = overround - 1.0

    return probs, margin


def _calc_kelly(posterior: list[float], odds: dict[str, float] | None, pick: str) -> float:
    """凯利公式: f* = (b·p - q) / b × 0.25 (1/4 Kelly)"""
    if not odds:
        return 0.0

    pick_idx = {"H": 0, "D": 1, "A": 2}[pick]
    pick_key = {0: "home", 1: "draw", 2: "away"}[pick_idx]
    decimal_odds = odds.get(pick_key, 2.0)

    p = posterior[pick_idx]
    q = 1 - p
    b = decimal_odds - 1  # net odds

    if b <= 0:
        return 0.0

    full_kelly = (b * p - q) / b
    # 1/4 Kelly (保守)
    quarter_kelly = max(0.0, full_kelly * 0.25)

    return quarter_kelly


# ============================================================
# 便捷: 批量处理
# ============================================================

def batch_bayesian(matches: list[dict]) -> list[dict]:
    """批量贝叶斯预测"""
    results = []
    for m in matches:
        result = bayesian_match_prediction(
            home_team=m.get("home", ""),
            away_team=m.get("away", ""),
            model_probs=m.get("model_probs", [0.4, 0.3, 0.3]),
            model_confidence=m.get("model_confidence", 0.5),
            pinnacle_odds=m.get("pinnacle_odds"),
            odds_dispersion=m.get("odds_dispersion", 0.04),
            avg_margin=m.get("avg_margin", 0.05),
        )
        results.append(result)
    return results
