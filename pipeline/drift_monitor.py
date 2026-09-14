# -*- coding: utf-8 -*-
"""输入侧漂移预警 (PSI) —— 事前信号, 而不是等 Brier 涨了才知道。

监控对象 (2026-09-13 立): 本模型的特征维度极低 (每队仅 攻/防 2 个内生参数 + ELO + 市场),
所以不能照搬"高维特征工程"那套 PSI。这里只盯三样真正会打坏预测的分布:
  1. 总进球分布   —— 直接决定大小球 / 双进球
  2. 胜平负构成   —— 直接决定 1X2 先验 (平局率尤其敏感)
  3. ELO 评级分布 —— 联赛整体实力结构与升降级换血

窗口: 参考窗 = [最新日 - recent - ref, 最新日 - recent), 当前窗 = [最新日 - recent, 最新日]
阈值 (行业惯例): PSI < 0.10 稳定 / 0.10~0.25 轻微漂移 / > 0.25 显著漂移

用法:
    python pipeline/drift_monitor.py
    python pipeline/drift_monitor.py --recent 30 --ref 365 --strict
输出: data/state/drift_report.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from models.elo import EloSystem  # noqa: E402
from pipeline.data_loader import load_all_csvs  # noqa: E402

KEEP = ("PL", "PD", "BL1", "SA", "FL1", "UCL")
GOAL_BINS = [0, 1, 2, 3, 4, 5]        # 6+ 归最后一档
GOAL_LABELS = ["0", "1", "2", "3", "4", "5", "6+"]
ELO_BINS = [0, 1400, 1475, 1525, 1600, 1700, 9999]
ELO_LABELS = ["<1400", "1400-1475", "1475-1525", "1525-1600", "1600-1700", ">1700"]

MINOR, MAJOR = 0.10, 0.25


def _bucket(v: float, edges: list[int]) -> int:
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i
    return len(edges) - 2


def _shares(values: list[float], edges: list[int], nbin: int) -> list[float]:
    if not values:
        return [0.0] * nbin
    c = [0] * nbin
    for v in values:
        c[_bucket(v, edges)] += 1
    n = float(len(values))
    return [x / n for x in c]


def psi(ref: list[float], cur: list[float]) -> float:
    """群体稳定性指标 PSI = Σ (cur-r) · ln(cur/r)。份额为 0 时用 1e-4 兜底, 避免 log(0)。"""
    import math
    out = 0.0
    for r, c in zip(ref, cur):
        r = max(float(r), 1e-4)
        c = max(float(c), 1e-4)
        out += (c - r) * math.log(c / r)
    return out


# 小样本闸门 (2026-09-13): 当前窗每联赛只有 18~41 场时, 单场进球就能把 PSI 推到 0.4+,
# 那是样本噪声不是漂移 (实测 BL1 n=18 → PSI 0.481, 但全联赛口径 251 场只有 0.054)。
# 样本不足就不出判定, 避免狼来了。
MIN_N = 60


def _verdict(v: float, n: int = 10 ** 6) -> str:
    if n < MIN_N:
        return "样本不足"
    if v > MAJOR:
        return "显著漂移"
    if v > MINOR:
        return "轻微漂移"
    return "稳定"


def main() -> int:
    ap = argparse.ArgumentParser(description="PSI 漂移预警")
    # 默认 90 天: 30 天窗下每联赛只有约 30 场, 一律落进"样本不足"闸门, 监控等于没开。
    # 90 天每联赛约 90~100 场, 既有统计意义又能反映赛季内的风格变化。
    ap.add_argument("--recent", type=int, default=90, help="当前窗天数 (默认90)")
    ap.add_argument("--ref", type=int, default=365, help="参考窗天数 (默认365)")
    ap.add_argument("--strict", action="store_true", help="任一显著漂移即以退出码2结束")
    a = ap.parse_args()

    ms = [m for m in load_all_csvs() if m.get("date")]
    ms.sort(key=lambda m: m["date"])
    if not ms:
        print("没有历史数据, 无法监控")
        return 1
    latest = date.fromisoformat(str(ms[-1]["date"])[:10])
    cur_lo = latest - timedelta(days=a.recent)
    ref_hi = cur_lo
    ref_lo = ref_hi - timedelta(days=a.ref)

    def _d(m):
        return date.fromisoformat(str(m["date"])[:10])

    cur = [m for m in ms if cur_lo <= _d(m) <= latest]
    ref = [m for m in ms if ref_lo <= _d(m) < ref_hi]

    print("漂移监控 · 最新比赛日 %s" % latest)
    print("  当前窗 %s ~ %s : %d 场" % (cur_lo, latest, len(cur)))
    print("  参考窗 %s ~ %s : %d 场" % (ref_lo, ref_hi, len(ref)))
    if len(cur) < 30:
        print("  [警告] 当前窗样本仅 %d 场, PSI 不稳, 仅作参考" % len(cur))

    report = {
        "generated_for": str(latest),
        "window": {"recent_days": a.recent, "ref_days": a.ref,
                   "cur": str(cur_lo) + "~" + str(latest), "ref": str(ref_lo) + "~" + str(ref_hi),
                   "n_cur": len(cur), "n_ref": len(ref)},
        "leagues": {},
    }

    print()
    hdr = "%-6s %-6s %-8s %-9s %-8s %-8s %-9s" % ("联赛", "场次", "进球PSI", "判定", "主胜", "平局", "客胜")
    print(hdr)
    print("-" * len(hdr))
    worst = 0.0
    rows = list(KEEP) + ["ALL"]
    for lg in rows:
        c = cur if lg == "ALL" else [m for m in cur if m["league_code"] == lg]
        r = ref if lg == "ALL" else [m for m in ref if m["league_code"] == lg]
        if len(c) < 10 or len(r) < 10:
            continue
        gp = psi(_shares([m["home_goals"] + m["away_goals"] for m in r], GOAL_BINS, 6),
                 _shares([m["home_goals"] + m["away_goals"] for m in c], GOAL_BINS, 6))
        rp = psi(_shares([m["home_goals"] - m["away_goals"] for m in r], [-9, 0, 1, 99], 3),
                 _shares([m["home_goals"] - m["away_goals"] for m in c], [-9, 0, 1, 99], 3))
        hw = sum(1 for m in c if m["home_goals"] > m["away_goals"]) / len(c)
        dr = sum(1 for m in c if m["home_goals"] == m["away_goals"]) / len(c)
        aw = 1.0 - hw - dr
        vd = _verdict(gp, len(c))
        # ALL 口径永远参与"最大 PSI"统计 (样本量足够); 分联赛只有过闸门才算
        if lg == "ALL" or vd in ("显著漂移", "轻微漂移"):
            worst = max(worst, gp)
        print("%-6s %-6d %-8.3f %-9s %-8.1f%% %-8.1f%% %-9.1f%%" % (
            lg, len(c), gp, vd, hw * 100, dr * 100, aw * 100))
        report["leagues"][lg] = {
            "n_cur": len(c), "n_ref": len(r),
            "psi_goals": round(gp, 4), "psi_result": round(rp, 4),
            "verdict": _verdict(max(gp, rp), len(c)),
            "cur_home_win": round(hw, 4), "cur_draw": round(dr, 4), "cur_away_win": round(aw, 4),
        }

    # ── ELO 评级分布漂移 (重放到两个时点各取一次快照) ──
    def _elo_snapshot(cutoff: str, window_matches: list[dict]) -> dict:
        """重放到 cutoff 为止, 返回"在该窗口出过场的球队"的评级 {队名: ELO}。
        返回字典(不是列表)是为了下面能按队名取两个窗口的交集。"""
        e = EloSystem()
        e.initialize_from_matches([m for m in ms if str(m["date"])[:10] < cutoff])
        teams = {m["home_team"] for m in window_matches} | {m["away_team"] for m in window_matches}
        return {t: e._ratings[t] for t in teams if t in e._ratings}

    # 只比"两个窗口都出现过的球队"。否则 PSI 量到的是升降级换血 (参考窗摊了一整个
    # 赛季 225 队, 当前窗只有 120 队), 那会把换血误报成评级漂移, 每周都喊狼来了。
    # 换血本身另立一个 roster_overlap 指标单独看。
    try:
        e_ref = _elo_snapshot(str(ref_hi), ref)
        e_cur = _elo_snapshot(str(latest) + "~", cur)
        common_ref = {t: v for t, v in e_ref.items() if t in e_cur}
        common_cur = {t: v for t, v in e_cur.items() if t in e_ref}
        names = sorted(common_cur)
        r_vals = [common_ref[t] for t in names]
        c_vals = [common_cur[t] for t in names]
        overlap = len(common_cur) / max(len(e_cur), 1)
        print()
        if len(names) >= 60:
            pe = psi(_shares(r_vals, ELO_BINS, len(ELO_LABELS)),
                     _shares(c_vals, ELO_BINS, len(ELO_LABELS)))
            vd = _verdict(pe, len(names))
            print("ELO 评级漂移 PSI = %.3f  (%s)   共同球队 %d 支" % (pe, vd, len(names)))
            report["elo"] = {"psi": round(pe, 4), "verdict": vd, "n_common": len(names),
                             "n_ref": len(e_ref), "n_cur": len(e_cur)}
            if vd in ("显著漂移", "轻微漂移"):
                worst = max(worst, pe)
        else:
            print("ELO 评级漂移: 共同球队仅 %d 支, 样本不足" % len(names))
            report["elo"] = {"n_common": len(names), "verdict": "样本不足"}
        print("  名单换血: 当前窗 %d 队中 %.0f%% 在参考窗出现过 (新面孔 %d 队)" % (
            len(e_cur), overlap * 100, len(e_cur) - len(common_cur)))
        report["roster_overlap"] = round(overlap, 4)
        report["n_new_teams"] = len(e_cur) - len(common_cur)
    except Exception as e:
        print()
        print("ELO 漂移计算跳过: %s" % str(e)[:80])
        report["elo"] = {"error": str(e)[:120]}

    report["worst_psi"] = round(worst, 4)
    report["verdict"] = _verdict(worst)
    os.makedirs("data/state", exist_ok=True)
    with open(os.path.join("data", "state", "drift_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print()
    print("总判定: %s (最大 PSI %.3f)  → data/state/drift_report.json" % (_verdict(worst), worst))
    if a.strict and worst > MAJOR:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
