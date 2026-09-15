# -*- coding: utf-8 -*-
"""队名未匹配队列 —— 把"结算不上"从人肉踩坑变成系统报账。

背景 (2026-09-15): 队名打通一直是人工补丁驱动的, 同类故障已复现 4 次
(Rennes / Brest / 勒芒 / Parma-Inter)。每次都是"复盘发现缺场次 → 我手工钉进
CURATED"。这个工具把它反过来: 复盘/预测两侧对不上的名字自动进队列, 由系统提示,
不再等人撞上去。

用法:
    python tools/check_unmatched.py            # 扫描全部有赛果的日期
    python tools/check_unmatched.py --days 14  # 只看最近 N 天
输出:
    控制台报告 + data/state/unmatched_names.json (累积队列, 记录次数与最近日期)
"""
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline.result_fetcher import _teams_match  # noqa: E402

QUEUE = os.path.join("data", "state", "unmatched_names.json")


def _load() -> dict:
    if os.path.exists(QUEUE):
        try:
            return json.load(open(QUEUE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _note(q: dict, name: str, side: str, date: str) -> None:
    if not name:
        return
    e = q.setdefault(name, {"side": side, "count": 0, "first": date, "last": date})
    e["count"] += 1
    e["last"] = max(e.get("last", date), date)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="只看最近 N 天 (0=全部)")
    a = ap.parse_args()

    dates = sorted({os.path.basename(f)[len("predictions_"):-len(".json")]
                    for f in glob.glob("data/output/predictions_????-??-??.json")})
    if a.days:
        dates = dates[-a.days:]

    q = _load()
    new_hits = 0
    day_rows = []
    for d in dates:
        pf = "data/output/predictions_%s.json" % d
        rf = "data/output/results_%s.json" % d
        if not (os.path.exists(pf) and os.path.exists(rf)):
            continue
        try:
            P = json.load(open(pf, encoding="utf-8"))
            R = json.load(open(rf, encoding="utf-8"))
        except Exception:
            continue
        # 赛果侧: 没有任何预测能对上 → 记下来
        orphan = []
        for x in R:
            ok = any(_teams_match(p.get("home_team", ""), x.get("home_team", ""))
                     and _teams_match(p.get("away_team", ""), x.get("away_team", ""))
                     for p in P)
            if not ok:
                orphan.append(x)
        # 预测侧: 没有任何赛果能对上 → 尚未结算
        unsettled = []
        for p in P:
            ok = any(_teams_match(p.get("home_team", ""), x.get("home_team", ""))
                     and _teams_match(p.get("away_team", ""), x.get("away_team", ""))
                     for x in R)
            if not ok:
                unsettled.append(p)
        if orphan or unsettled:
            day_rows.append((d, len(orphan), len(unsettled)))
            for x in orphan:
                for side in ("home_team", "away_team"):
                    _note(q, x.get(side, ""), "赛果", d)
                    new_hits += 1
            for p in unsettled:
                for side in ("home_team", "away_team"):
                    _note(q, p.get(side, ""), "预测", d)
                    new_hits += 1

    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    json.dump(q, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if day_rows:
        print("存在未匹配的日期 (日期 / 孤儿赛果 / 未结算预测):")
        for d, no, nu in day_rows[-12:]:
            print("  %s   %d / %d" % (d, no, nu))
    else:
        print("所有日期两侧都完全匹配 ✓")
    print()
    # 只报"本次扫描窗口内还出现过"的 —— 否则会被 09-09 范围纪律之前的旧噪音淹没
    # (那之前我们还会预测本菲卡/萨尔茨堡这类非五大球队)
    cut = min(dates) if dates else "0000-00-00"
    fresh = {k: v for k, v in q.items() if str(v.get("last", "")) >= cut}
    print("累积未匹配队名 %d 个 (其中近期 %d 个, 存在 %s)" % (len(q), len(fresh), QUEUE))
    top = sorted(fresh.items(), key=lambda kv: -kv[1]["count"])[:15]
    for nm, e in top:
        print("  %-32s %s侧  出现 %d 次  最近 %s" % (nm[:32], e["side"], e["count"], e["last"]))
    if not q:
        print("  (空)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
