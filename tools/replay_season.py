# -*- coding: utf-8 -*-
"""用当前模型把开赛以来重新预测一遍, 并对照赛果出命中率。

为什么这么做而不另写回测:
  data/state/odds_snapshots/ 里按日留了当时的完整输入(含赔率, 与 today.json 同 schema),
  用它重建输入后直接调 pipeline.py predict —— 模型、市场融合、平局校准、冷启动、
  聚焦联赛过滤全部与线上一致。另写一套回测最容易出的就是"口径漂移"。

用法:
    python tools/replay_season.py --test 2       # 只跑最近2天, 先验通道
    python tools/replay_season.py                # 全量重跑 + 评估
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SNAP = "data/state/odds_snapshots"
OUT = "data/replay"


def snapshots_by_date() -> dict:
    """{日期: 该日场次最多的那份快照路径}"""
    per = {}
    for fp in sorted(glob.glob(os.path.join(SNAP, "*.json"))):
        m = re.match(r"snapshot_(\d{4}-\d{2}-\d{2})_", os.path.basename(fp))
        if not m:
            continue
        d = m.group(1)
        try:
            n = len(json.load(open(fp, encoding="utf-8")))
        except Exception:
            continue
        if d not in per or n > per[d][1]:
            per[d] = (fp, n)
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, default=0, help="只跑最近 N 天做通道验证")
    ap.add_argument("--eval-only", action="store_true", help="跳过重放, 只评估已有结果")
    a = ap.parse_args()

    if a.eval_only:
        evaluate()
        return

    per = snapshots_by_date()
    dates = sorted(per)
    if a.test:
        dates = dates[-a.test:]
    print("可重放日期 %d 天: %s ~ %s" % (len(dates), dates[0], dates[-1]))

    os.makedirs(OUT, exist_ok=True)
    os.makedirs("data/replay_tmp", exist_ok=True)
    for i, d in enumerate(dates, 1):
        fp, n = per[d]
        mj = os.path.join("data", "replay_tmp", "today.json")
        shutil.copyfile(fp, mj)
        od = os.path.join(OUT, d)
        if os.path.isdir(od):
            shutil.rmtree(od)
        os.makedirs(od, exist_ok=True)
        print("[%d/%d] %s ← %s (%d 场)" % (i, len(dates), d, os.path.basename(fp), n))
        # 重放绝不能写公示哈希链台账 (否则往对外存证里灌虚构记录)
        env = dict(os.environ)
        env["FOOTBALL_NO_FREEZE"] = "1"
        r = subprocess.run([sys.executable, "pipeline.py", "predict",
                            "--matches-json", mj, "--output-dir", od],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
        if r.returncode != 0:
            print("      失败: " + (r.stdout or "")[-300:] + (r.stderr or "")[-300:])
            continue
    print()
    print("重放完成 → %s" % OUT)
    if not a.test:
        evaluate()


def _devig(oh, od, oa):
    raw = [1.0 / oh, 1.0 / od, 1.0 / oa]
    s = sum(raw)
    return [x / s for x in raw]


def evaluate():
    """把重放结果与赛果对照。命中率口径: 线上显示的是贝叶斯后验(融合了市场),
    所以头条数字用后验; 纯模型单独列一行做对照。"""
    import math
    from pipeline.result_fetcher import _teams_match

    rows = []
    for od in sorted(glob.glob(os.path.join(OUT, "????-??-??"))):
        d = os.path.basename(od)
        pj = glob.glob(os.path.join(od, "predictions_*.json"))
        rf = os.path.join("data", "output", "results_%s.json" % d)
        if not pj or not os.path.exists(rf):
            continue
        preds = json.load(open(pj[0], encoding="utf-8"))
        res = json.load(open(rf, encoding="utf-8"))
        for p in preds:
            act = None
            for x in res:
                if _teams_match(p["home_team"], x["home_team"]) and _teams_match(p["away_team"], x["away_team"]):
                    h, g = x["home_goals"], x["away_goals"]
                    act = "H" if h > g else ("D" if h == g else "A")
                    break
            if act is None:
                continue
            mk = p.get("model") or {}
            po = (p.get("bayesian") or {}).get("posterior") or {}
            od_ = p.get("odds") or {}
            rows.append({"date": d, "lg": p.get("league_code"), "act": act,
                         "model": [mk.get("home_win"), mk.get("draw"), mk.get("away_win")],
                         "post": [po.get("home"), po.get("draw"), po.get("away")],
                         "odds": [od_.get("home"), od_.get("draw"), od_.get("away")]})
    if not rows:
        print("没有可对照的赛果")
        return

    def _score(p, act):
        if not p or any(x is None for x in p):
            return None
        k = "HDA".index(act)
        o = [0.0, 0.0, 0.0]
        o[k] = 1.0
        brier = sum((p[i] - o[i]) ** 2 for i in range(3))
        ll = -math.log(max(p[k], 1e-12))
        return brier, ll, ("HDA"[p.index(max(p))] == act)

    print()
    print("=" * 74)
    print("开赛以来 · 当前模型重新预测 · 命中率  (共 %d 场可结算)" % len(rows))
    print("=" * 74)
    hdr = "%-16s %-7s %-9s %-9s %-9s" % ("口径", "场次", "方向命中", "Brier", "LogLoss")
    print(hdr)
    print("-" * len(hdr))
    for tag, key in (("模型(纯DC+ELO)", "model"), ("线上显示(融合后验)", "post")):
        n = hit = 0
        bs = ls = 0.0
        for r in rows:
            s = _score(r[key], r["act"])
            if not s:
                continue
            bs += s[0]
            ls += s[1]
            hit += s[2]
            n += 1
        if n:
            print("%-16s %-7d %-9s %-9.4f %-9.4f" % (tag, n, "%.1f%%" % (hit / n * 100), bs / n, ls / n))
    n = hit = 0
    bs = 0.0
    for r in rows:
        if any(x is None for x in r["odds"]):
            continue
        # 体彩抽水约 13%, 1/赔率之和应在 1.0~2.0。偏出这个区间说明该条不是原始
        # 十进制赔率(输入缺赔率时 pipeline 会用派生值覆盖 odds 字段), 直接丢弃,
        # 否则会把"市场参考线"算成 49% 这种假数字。
        if not (1.0 <= sum(1.0 / x for x in r["odds"]) <= 2.0):
            continue
        p = _devig(*r["odds"])
        s = _score(p, r["act"])
        if not s:
            continue
        bs += s[0]
        hit += s[2]
        n += 1
    if n:
        print("%-16s %-7d %-9s %-9.4f %-9s" % ("市场(去水)", n, "%.1f%%" % (hit / n * 100), bs / n, "—"))
    print()
    print("分联赛 (线上显示口径):")
    by = {}
    for r in rows:
        s = _score(r["post"], r["act"])
        if s:
            by.setdefault(r["lg"], []).append(s)
    for lg in sorted(by):
        v = by[lg]
        print("  %-5s n=%-5d 命中 %5.1f%%   Brier %.4f" % (
            lg, len(v), sum(1 for x in v if x[2]) / len(v) * 100, sum(x[0] for x in v) / len(v)))


if __name__ == "__main__":
    main()
