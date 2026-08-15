# -*- coding: utf-8 -*-
"""
概率校准模块 (Phase 2 · 2026-08-15)

对 Dixon-Coles 1X2 输出做保序回归 (PAV) 校准:
  模型概率系统偏差 (如高估热门、低估平局) 通过训练集真实频率校正。

实现:
  fit_calibration(preds, actuals)    → 每个结果 (H/D/A) 的校准映射 (10桶 + PAV平滑)
  apply_calibration(probs, cal)      → 校准后概率
  save/load                          → data/state/calibration.json

注意: 校准只在训练数据上拟合, 在测试/实盘上应用; 回测折内自动重拟合。
"""
from __future__ import annotations

import json
import os
from typing import Any


def _pav(sorted_points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pool Adjacent Violators: 单调化 (预测概率 → 实际频率) 曲线"""
    if not sorted_points:
        return []
    # 分组: [count, sum_x, sum_y]
    groups: list[list[float]] = [[1.0, p, y] for p, y in sorted_points]
    i = 0
    while i < len(groups) - 1:
        if groups[i][2] / groups[i][0] > groups[i + 1][2] / groups[i + 1][0]:
            # 违反单调性 → 合并
            c, sx, sy = groups[i]
            c2, sx2, sy2 = groups[i + 1]
            groups[i] = [c + c2, sx + sx2, sy + sy2]
            groups.pop(i + 1)
            if i > 0:
                i -= 1
        else:
            i += 1
    return [(sx / c, sy / c) for c, sx, sy in groups]


def fit_calibration(
    pred_probs: list[list[float]],
    actuals: list[int],
    n_bins: int = 10,
) -> dict[str, Any]:
    """拟合 3-way 概率校准 (H/D/A 独立)

    Args:
        pred_probs: [[p_home, p_draw, p_away], ...]
        actuals:    [0, 1, 2] (H/D/A 下标)

    Returns:
        {"bins": [...], "curves": {"H": [[x,y]...], "D": ..., "A": ...}}
    """
    n = len(pred_probs)
    if n < 200:
        return {"bins": [], "curves": {"H": [], "D": [], "A": []}, "n": n}

    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    curves: dict[str, list[tuple[float, float]]] = {"H": [], "D": [], "A": []}

    for outcome, key in enumerate(["H", "D", "A"]):
        # 按预测概率分桶, 统计实际频率
        pairs = sorted((pred_probs[i][outcome], 1.0 if actuals[i] == outcome else 0.0) for i in range(n))
        bin_points: list[tuple[float, float]] = []
        step = n / n_bins
        for b in range(n_bins):
            lo = int(b * step)
            hi = int((b + 1) * step)
            chunk = pairs[lo:hi]
            if not chunk:
                continue
            x = sum(p for p, _ in chunk) / len(chunk)
            y = sum(y for _, y in chunk) / len(chunk)
            bin_points.append((x, y))
        curves[key] = _pav(bin_points)

    return {"bins": bin_edges, "curves": curves, "n": n}


def _interp(x: float, curve: list[tuple[float, float]]) -> float:
    """在单调校准曲线上线性插值"""
    if not curve:
        return x
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        x0, y0 = curve[i]
        x1, y1 = curve[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return (y0 + y1) / 2
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return x


def apply_calibration(probs: list[float], cal: dict[str, Any] | None) -> list[float]:
    """校准一组 H/D/A 概率"""
    if not cal or not cal.get("curves"):
        return probs
    curves = cal["curves"]
    out = [
        _interp(probs[0], curves.get("H", [])),
        _interp(probs[1], curves.get("D", [])),
        _interp(probs[2], curves.get("A", [])),
    ]
    # 归一化
    total = sum(out)
    if total > 0:
        out = [v / total for v in out]
    return out


def save_calibration(cal: dict[str, Any], path: str = "data/state/calibration.json") -> None:
    """保存校准映射"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)


def load_calibration(path: str = "data/state/calibration.json") -> dict[str, Any] | None:
    """加载校准映射; 不存在返回 None"""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
