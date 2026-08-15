"""
多维度复盘 · v1.0 (2026-08-13)

核心原则: 每个维度是独立预测任务，独立计分、独立累计。
- 1X2   胜平负方向 (3-way)
- OU25  大小球 2.5 (2-way)
- OU35  大小球 3.5 (2-way)
- BTTS  双方进球 (2-way)
- AH    让球盘 (2-way, 需today.json盘口)

维度门禁 (样本≥30后启用):
- 2-way维度: Brier < 0.25 (p=0.5基线) 且 准确率 > 52%
- 3-way维度: Brier < 0.65
未过门的维度不产生投注信号。
"""
from __future__ import annotations

import json
import os
import math
from typing import Any


def _dc_score_matrix(lam_h: float, lam_a: float, rho: float, max_g: int = 8) -> list[list[float]]:
    """Dixon-Coles比分矩阵 — 从λh/λa/ρ重建"""
    import math as m
    mat = [[0.0] * (max_g + 1) for _ in range(max_g + 1)]
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            p = m.exp(-lam_h) * lam_h ** i / m.factorial(i)
            p *= m.exp(-lam_a) * lam_a ** j / m.factorial(j)
            # DC tau修正
            if i == 0 and j == 0:
                p *= 1 - lam_h * lam_a * rho
            elif i == 0 and j == 1:
                p *= 1 + lam_h * rho
            elif i == 1 and j == 0:
                p *= 1 + lam_a * rho
            elif i == 1 and j == 1:
                p *= 1 - rho
            mat[i][j] = p
    # 归一化
    total = sum(sum(row) for row in mat)
    return [[v / total for v in row] for row in mat]


def ah_probabilities(lam_h: float, lam_a: float, rho: float, line: float) -> dict:
    """让球盘概率 — line为盘口(负数=主让, 如-1.0)

    返回 {home_cover, push, away_cover}
    主队覆盖: hg - ag > -line
    走盘:     hg - ag == -line
    客队覆盖: hg - ag < -line
    """
    mat = _dc_score_matrix(lam_h, lam_a, rho)
    home_c, push_c, away_c = 0.0, 0.0, 0.0
    for i, row in enumerate(mat):
        for j, p in enumerate(row):
            diff = i - j
            if diff > -line:
                home_c += p
            elif diff == -line:
                push_c += p
            else:
                away_c += p
    return {"home_cover": home_c, "push": push_c, "away_cover": away_c}


def evaluate_dimensions(
    matched: list[dict],
    matches_info: dict[str, dict] | None = None,
) -> dict:
    """逐维度评估预测 vs 赛果

    Args:
        matched: match_predictions_to_results 的输出，每项含
            predicted(model dict), home_goals, away_goals, actual(H/D/A)
        matches_info: {home|away: {handicap}} 盘口信息(来自today.json)

    Returns:
        {
          "1X2":  {"n": int, "brier": float, "accuracy": float, "details": [...]},
          "OU25": {...}, "OU35": {...}, "BTTS": {...}, "AH": {...},
        }
    """
    dims = {
        "1X2": {"n": 0, "brier_sum": 0.0, "correct": 0, "details": []},
        "OU25": {"n": 0, "brier_sum": 0.0, "correct": 0, "details": []},
        "OU35": {"n": 0, "brier_sum": 0.0, "correct": 0, "details": []},
        "BTTS": {"n": 0, "brier_sum": 0.0, "correct": 0, "details": []},
        "AH": {"n": 0, "brier_sum": 0.0, "correct": 0, "details": []},
    }

    matches_info = matches_info or {}

    for m in matched:
        pred = m.get("predicted", m)
        gh = m.get("home_goals")
        ga = m.get("away_goals")
        if gh is None or ga is None:
            continue
        # Phase 1 A2: 无赔率冷启动场次不计入维度台账(预测无信息量)
        if m.get("no_signal"):
            continue
        total = gh + ga

        # ---- 1X2 ----
        h, d, a = pred.get("home_win", 0.33), pred.get("draw", 0.33), pred.get("away_win", 0.33)
        actual_vec = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}.get(m.get("actual", ""))
        if actual_vec:
            brier = sum((p - v) ** 2 for p, v in zip((h, d, a), actual_vec)) / 3
            pick = ("H", "D", "A")[max(range(3), key=lambda i: (h, d, a)[i])]
            dims["1X2"]["n"] += 1
            dims["1X2"]["brier_sum"] += brier
            dims["1X2"]["correct"] += int(pick == m["actual"])
            dims["1X2"]["details"].append({
                "home": m.get("home_team", ""), "away": m.get("away_team", ""),
                "score": f"{gh}-{ga}", "brier": round(brier, 4),
                "pick": pick, "actual": m["actual"], "hit": pick == m["actual"],
            })

        # ---- OU 2.5 ----
        p_over = pred.get("over_25")
        if p_over is not None:
            actual_over = 1 if total >= 3 else 0
            brier = (p_over - actual_over) ** 2
            pick_over = p_over >= 0.5
            hit = pick_over == bool(actual_over)
            dims["OU25"]["n"] += 1
            dims["OU25"]["brier_sum"] += brier
            dims["OU25"]["correct"] += int(hit)
            dims["OU25"]["details"].append({
                "home": m.get("home_team", ""), "away": m.get("away_team", ""),
                "score": f"{gh}-{ga}", "brier": round(brier, 4),
                "p_over": round(p_over, 3), "actual_over": bool(actual_over), "hit": hit,
            })

        # ---- OU 3.5 ----
        p_over35 = pred.get("over_35")
        if p_over35 is not None:
            actual_over = 1 if total >= 4 else 0
            brier = (p_over35 - actual_over) ** 2
            pick_over = p_over35 >= 0.5
            hit = pick_over == bool(actual_over)
            dims["OU35"]["n"] += 1
            dims["OU35"]["brier_sum"] += brier
            dims["OU35"]["correct"] += int(hit)
            dims["OU35"]["details"].append({
                "home": m.get("home_team", ""), "away": m.get("away_team", ""),
                "score": f"{gh}-{ga}", "brier": round(brier, 4),
                "p_over": round(p_over35, 3), "actual_over": bool(actual_over), "hit": hit,
            })

        # ---- BTTS ----
        p_btts = pred.get("btts")
        if p_btts is not None:
            actual_btts = 1 if (gh > 0 and ga > 0) else 0
            brier = (p_btts - actual_btts) ** 2
            pick_btts = p_btts >= 0.5
            hit = pick_btts == bool(actual_btts)
            dims["BTTS"]["n"] += 1
            dims["BTTS"]["brier_sum"] += brier
            dims["BTTS"]["correct"] += int(hit)
            dims["BTTS"]["details"].append({
                "home": m.get("home_team", ""), "away": m.get("away_team", ""),
                "score": f"{gh}-{ga}", "brier": round(brier, 4),
                "p_btts": round(p_btts, 3), "actual_btts": bool(actual_btts), "hit": hit,
            })

        # ---- AH 让球 ----
        lam_h = pred.get("lambda_home")
        lam_a = pred.get("lambda_away")
        rho = pred.get("rho")
        key = f'{m.get("home_team", "")}|{m.get("away_team", "")}'
        info = matches_info.get(key, {})
        line = info.get("handicap")
        # 队名标准化导致today.json查找失败时, 用预测自带的盘口兜底
        if line is None:
            ah_pred = m.get("ah_handicap")
            if isinstance(ah_pred, dict):
                line = ah_pred.get("goal_line")
            else:
                line = ah_pred
        if line is not None and lam_h is not None and lam_a is not None:
            ah = ah_probabilities(lam_h, lam_a, rho or 0.0, line)
            # 主队覆盖概率 (走盘概率平分)
            p_cover = ah["home_cover"] + ah["push"] / 2
            diff = gh - ga
            if diff > -line:
                actual_cover = 1
            elif diff == -line:
                actual_cover = 0.5  # 走盘
            else:
                actual_cover = 0
            brier = (p_cover - actual_cover) ** 2
            hit = (p_cover >= 0.5) == (actual_cover >= 0.5)
            dims["AH"]["n"] += 1
            dims["AH"]["brier_sum"] += brier
            dims["AH"]["correct"] += int(hit)
            dims["AH"]["details"].append({
                "home": m.get("home_team", ""), "away": m.get("away_team", ""),
                "score": f"{gh}-{ga}", "line": line, "brier": round(brier, 4),
                "p_cover": round(p_cover, 3), "actual": "主" if actual_cover == 1 else "走" if actual_cover == 0.5 else "客",
                "hit": hit,
            })

    # 汇总
    result = {}
    for dim, d in dims.items():
        n = d["n"]
        result[dim] = {
            "n": n,
            "brier": round(d["brier_sum"] / n, 4) if n else None,
            "accuracy": round(d["correct"] / n, 4) if n else None,
            "details": d["details"],
        }
    return result


def update_ledger(day_result: dict, ledger_path: str, date_str: str | None = None) -> dict:
    """累计维度成绩到 ledger 文件

    Args:
        day_result: evaluate_dimensions 的输出
        ledger_path: data/state/dimension_ledger.json
        date_str: 当日日期 (YYYY-MM-DD); 同日重复调用自动跳过 (幂等)

    Returns:
        更新后的 ledger
    """
    ledger = {"dimensions": {}, "updated_at": ""}
    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as f:
            ledger = json.load(f)

    from datetime import datetime
    ledger["updated_at"] = datetime.now().isoformat()

    for dim, d in day_result.items():
        if d["n"] == 0:
            continue
        L = ledger["dimensions"].setdefault(dim, {
            "n": 0, "brier_sum": 0.0, "correct": 0, "samples": [], "dates": [],
        })
        # 幂等: 同日重复 review 不重复累计
        if date_str and date_str in L.get("dates", []):
            continue
        L["n"] += d["n"]
        L["brier_sum"] += d["brier"] * d["n"]
        L["correct"] += round((d["accuracy"] or 0) * d["n"])
        L["brier"] = round(L["brier_sum"] / L["n"], 4)
        L["accuracy"] = round(L["correct"] / L["n"], 4)
        # 保留最近30条明细
        L["samples"] = (L["samples"] + d["details"])[-30:]
        if date_str:
            L["dates"] = (L.get("dates", []) + [date_str])[-30:]

    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    return ledger


def _climatology_brier(samples: list[dict], dim: str) -> float:
    """气候基线Brier = p(1-p) — 恒猜样本实际基率的最优预测"""
    n = len(samples)
    if n == 0:
        return 0.25
    if dim == "OU25" or dim == "OU35":
        p = sum(1 for s in samples if s.get("actual_over")) / n
    elif dim == "BTTS":
        p = sum(1 for s in samples if s.get("actual_btts")) / n
    elif dim == "AH":
        # 覆盖率: 主=1 走=0.5 客=0
        p = sum({"主": 1.0, "走": 0.5, "客": 0.0}.get(s.get("actual", "客"), 0.0) for s in samples) / n
    else:
        # 1X2: 恒猜样本中最常见结果
        from collections import Counter
        cnt = Counter(s.get("actual") for s in samples)
        p = max(cnt.values()) / n
    return round(p * (1 - p), 4)


def print_dimension_summary(day_result: dict, ledger: dict) -> str:
    """打印维度复盘总结，返回纯文本(供HTML复用)

    门禁: 模型Brier < 气候基线Brier (即比'恒猜多数派'更有信息量)
    """
    lines = []
    lines.append("维度复盘 (门禁: 模型Brier < 气候基线):")
    lines.append("-" * 56)
    names = {
        "1X2": "胜平负 (3-way)",
        "OU25": "大小球2.5 (2-way)",
        "OU35": "大小球3.5 (2-way)",
        "BTTS": "双方进球 (2-way)",
        "AH": "让球盘 (2-way)",
    }
    for dim in ["1X2", "OU25", "OU35", "BTTS", "AH"]:
        d = day_result[dim]
        L = ledger.get("dimensions", {}).get(dim, {})
        if d["n"] == 0:
            lines.append(f"  {dim:<6} {names[dim]:<24} 今日无样本")
            continue
        # 气候基线用累计样本算
        all_samples = (L.get("samples", []) + d["details"])[-200:]
        clim = _climatology_brier(all_samples, dim)
        status = ""
        if d["brier"] is not None:
            gate_ok = d["brier"] < clim
            status = "✅有技能" if gate_ok else "❌无技能"
        lines.append(
            f"  {dim:<6} {names[dim]:<20} 今日{d['n']}场 "
            f"Brier {d['brier']} vs 基线{clim} {status}"
        )
        if L.get("n"):
            L_samples = L.get("samples", [])
            L_clim = _climatology_brier(L_samples, dim)
            L_status = "✅" if L["brier"] < L_clim else "❌"
            lines.append(
                f"        累计{L['n']}场 Brier {L['brier']} vs 基线{L_clim} 命中{L['accuracy']:.0%} {L_status}"
            )
    return "\n".join(lines)


def load_matches_info(date_str: str) -> dict[str, dict]:
    """从 today.json 加载盘口信息 {home|away: {handicap}}"""
    path = f"data/today.json"
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        matches = json.load(f)
    from pipeline.data_loader import normalize_team_name
    info = {}
    for m in matches:
        # 标准化队名 — 与match_predictions_to_results的键对齐
        h = normalize_team_name(m.get("home_team", ""))
        a = normalize_team_name(m.get("away_team", ""))
        key = f"{h}|{a}"
        entry = {}
        if m.get("handicap") is not None:
            entry["handicap"] = m["handicap"]
        if m.get("odds"):
            entry["odds"] = m["odds"]
        info[key] = entry
    return info
