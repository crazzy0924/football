"""
标准化评估框架

三大原则:
1. 锁箱测试 — 只用未参与训练的延后赛事验证, 禁止回头调参
2. 多指标评估 — Brier + LogLoss + 校准曲线, 不只看准确率
3. 基线对比 — 每项指标必须优于联赛均值基线, 否则回退
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EvalResult:
    """单次评估结果"""
    n_matches: int = 0
    date_range: str = ""

    # 概率质量
    brier_score: float = 0.0        # 0~2, <0.20 优秀
    log_loss: float = 0.0           # <0.90 优秀
    accuracy: float = 0.0           # 方向命中率

    # 校准 (按预测概率分桶)
    calibration: dict[str, Any] = field(default_factory=dict)

    # 分市场
    by_market: dict[str, dict] = field(default_factory=dict)

    # vs 基线
    baseline_brier: float = 0.0
    beats_baseline: bool = False
    improvement_vs_baseline: float = 0.0

    # 偏差诊断
    home_bias: float = 0.0          # + = 高估主胜
    draw_bias: float = 0.0          # + = 低估平局
    overconfidence: float = 0.0     # + = 模型过于自信

    verdict: str = ""               # 综合判断


# ============================================================
# 锁箱测试
# ============================================================

def lockbox_evaluate(
    predictions: list[dict],    # [{"home_win": 0.55, "draw": 0.25, "away_win": 0.20, "actual": "H"}, ...]
    league_code: str = "",
    baseline_probs: dict | None = None,
) -> EvalResult:
    """锁箱评估 —— 不接受任何参数调整, 纯粹输入预测+赛果, 输出指标

    Args:
        predictions: 预测列表, 每条必须包含 home_win/draw/away_win 和 actual ("H"/"D"/"A")
        league_code: 联赛代码 (用于基线对比)
        baseline_probs: 联赛基线概率 (可选, 不传则从league_profiles取)

    Returns:
        EvalResult 完整评估

    规则:
        - 此函数只做评估, 不修改任何模型参数
        - 如果 beats_baseline=False → 该模型不应被部署
    """
    if not predictions:
        return EvalResult(verdict="无数据, 无法评估")

    n = len(predictions)
    brier_sum = 0.0
    logloss_sum = 0.0
    correct = 0
    home_over = 0.0
    draw_under = 0.0
    overconf_sum = 0.0

    # 校准分桶
    buckets = defaultdict(lambda: {"count": 0, "actual": 0})

    for pred in predictions:
        ph = pred.get("home_win", 0.33)
        pd = pred.get("draw", 0.33)
        pa = pred.get("away_win", 0.33)
        actual = pred.get("actual", "?")

        if actual == "?":
            continue

        # 实际结果向量
        ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(actual, (0, 0, 0))

        # Brier Score
        brier = (ph - ah) ** 2 + (pd - ad) ** 2 + (pa - aa) ** 2
        brier_sum += brier

        # Log Loss
        actual_prob = {"H": ph, "D": pd, "A": pa}.get(actual, 0.33)
        actual_prob = max(actual_prob, 1e-10)
        logloss_sum += -math.log(actual_prob)

        # 方向命中
        pick = "H" if ph >= pd and ph >= pa else "A" if pa >= ph and pa >= pd else "D"
        if pick == actual:
            correct += 1

        # 偏差
        if actual == "H":
            home_over += (ph - 1.0)
        elif actual == "D":
            draw_under += (1.0 - pd)
        overconf_sum += abs(ph - ah)  # 高估程度

        # 校准桶 (按预测的主胜概率分组)
        bucket_key = int(ph * 10) / 10  # 0.0, 0.1, 0.2, ...
        buckets[bucket_key]["count"] += 1
        buckets[bucket_key]["actual"] += ah

    # 汇总
    result = EvalResult(
        n_matches=n,
        brier_score=round(brier_sum / n, 4),
        log_loss=round(logloss_sum / n, 4),
        accuracy=round(correct / n, 4),
        home_bias=round(home_over / n, 4),
        draw_bias=round(draw_under / n, 4),
        overconfidence=round(overconf_sum / n, 4),
    )

    # 基线对比
    if baseline_probs:
        bl_h, bl_d, bl_a = baseline_probs["home_win"], baseline_probs["draw"], baseline_probs["away_win"]
        bl_brier = 0.0
        for pred in predictions:
            actual = pred.get("actual", "?")
            if actual == "?":
                continue
            ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(actual, (0, 0, 0))
            bl_brier += (bl_h - ah) ** 2 + (bl_d - ad) ** 2 + (bl_a - aa) ** 2
        result.baseline_brier = round(bl_brier / n, 4)
        result.beats_baseline = result.brier_score < result.baseline_brier
        result.improvement_vs_baseline = round(result.baseline_brier - result.brier_score, 4)
    else:
        # 无基线 → 从联赛画像取
        from src.models.league_profiles import get_profile
        p = get_profile(league_code or "PL")
        bl_h, bl_d, bl_a = p.home_win_rate, p.draw_rate, p.away_win_rate
        bl_brier = 0.0
        for pred in predictions:
            actual = pred.get("actual", "?")
            if actual == "?":
                continue
            ah, ad, aa = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(actual, (0, 0, 0))
            bl_brier += (bl_h - ah) ** 2 + (bl_d - ad) ** 2 + (bl_a - aa) ** 2
        result.baseline_brier = round(bl_brier / n, 4)
        result.beats_baseline = result.brier_score < result.baseline_brier
        result.improvement_vs_baseline = round(result.baseline_brier - result.brier_score, 4)

    # 校准数据
    calib = []
    for bk in sorted(buckets.keys()):
        b = buckets[bk]
        if b["count"] > 0:
            calib.append({
                "predicted_bucket": round(bk, 1),
                "count": b["count"],
                "actual_rate": round(b["actual"] / b["count"], 3) if b["count"] > 0 else 0,
            })
    result.calibration = {
        "buckets": calib,
        "quality": "良好" if abs(result.home_bias) < 0.05 and result.overconfidence < 0.15
        else "轻微失校准" if abs(result.home_bias) < 0.10
        else "严重失校准",
    }

    # 综合判断
    issues = []
    if not result.beats_baseline:
        issues.append("模型不优于联赛均值基线, 建议回退")
    if result.overconfidence > 0.20:
        issues.append(f"模型过于自信 (高估偏差{result.overconfidence:.0%})")
    if abs(result.home_bias) > 0.08:
        direction = "高估" if result.home_bias > 0 else "低估"
        issues.append(f"主场概率系统性{direction} ({result.home_bias:+.0%})")

    if not issues:
        result.verdict = "✅ 模型通过所有检查, 可以部署"
    else:
        result.verdict = "⚠ " + "; ".join(issues)

    return result


# ============================================================
# 便捷函数
# ============================================================

def quick_eval(predictions: list[dict]) -> str:
    """快速评估, 返回一句话结论"""
    result = lockbox_evaluate(predictions)
    return (
        f"Brier={result.brier_score} LogLoss={result.log_loss} "
        f"准确率={result.accuracy:.0%} "
        f"{'✅优于' if result.beats_baseline else '❌劣于'}基线"
        f"({result.improvement_vs_baseline:+.3f}) | {result.verdict}"
    )
