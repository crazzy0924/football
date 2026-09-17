# -*- coding: utf-8 -*-
"""验证"极端低赔陷阱": 热门赔率 <=1.15 时, 实际打出率是否显著低于隐含概率。

来源: 外部技能 football-analysis 的断言 —— "极端赔率 <=1.15 的场次,
      实际打出概率低于隐含概率约 40%"。
做法: 用本系统语料里的 Pinnacle 赔率去水 → 取热门方 → 分档对比
      "隐含概率均值" 与 "实际命中率", 并算押热门的 ROI。
判定: 差值的 t 值 |t|>2 才算真规律; 否则记为"不成立"。
用法: python tools/test_extreme_favorite.py
"""
import io, math, sys, glob, os, csv
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FIVE = {"E0": "PL", "SP1": "PD", "D1": "BL1", "I1": "SA", "F1": "FL1"}


def f(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def main():
    rows = []
    for fp in glob.glob(os.path.join("data", "historical_odds", "*.csv")):
        base = os.path.basename(fp)
        code = base.split("_")[0]
        with io.open(fp, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                try:
                    hg, ag = int(r["FTHG"]), int(r["FTAG"])
                except (KeyError, ValueError):
                    continue
                oh = f(r.get("PSH")) or f(r.get("B365H"))
                od = f(r.get("PSD")) or f(r.get("B365D"))
                oa = f(r.get("PSA")) or f(r.get("B365A"))
                if not (oh and od and oa):
                    continue
                raw = [1.0 / oh, 1.0 / od, 1.0 / oa]
                s = sum(raw)
                if not (1.0 <= s <= 1.25):      # 只吃正常抽水区间
                    continue
                pr = [x / s for x in raw]
                fav = pr.index(max(pr))
                odds = [oh, od, oa][fav]
                won = (0 if hg > ag else (1 if hg == ag else 2)) == fav
                rows.append({
                    "lg": code, "five": code in FIVE,
                    "odds": odds, "p": max(pr), "won": won,
                })
    print("可用样本 %d 场 (含五大 %d 场)" % (len(rows), sum(1 for x in rows if x["five"])))

    buckets = [(1.00, 1.15), (1.15, 1.30), (1.30, 1.50), (1.50, 1.80),
               (1.80, 2.20), (2.20, 3.00), (3.00, 99)]
    print()
    hdr = "%-12s %-8s %-11s %-11s %-10s %-8s %-9s %s" % (
        "热门赔率", "场次", "隐含均值", "实际命中", "差(pp)", "相对差", "ROI", "t 值")
    print(hdr)
    print("-" * len(hdr))
    for lo, hi in buckets:
        seg = [x for x in rows if lo <= x["odds"] < hi]
        if len(seg) < 30:
            continue
        n = len(seg)
        mp = sum(x["p"] for x in seg) / n
        ma = sum(1 for x in seg if x["won"]) / n
        d = [seg[i]["p"] - (1.0 if seg[i]["won"] else 0.0) for i in range(n)]
        mu = sum(d) / n
        sd = (sum((v - mu) ** 2 for v in d) / (n - 1)) ** 0.5
        se = sd / math.sqrt(n) if n else 0
        t = mu / se if se else 0.0
        pnl = sum((seg[i]["odds"] - 1.0) if seg[i]["won"] else -1.0 for i in range(n))
        rel = (ma - mp) / mp * 100
        print("%-12s %-8d %-11.4f %-11.4f %+.4f  %+.1f%%   %+7.1f%%  %+.2f" % (
            "%.2f-%.2f" % (lo, hi), n, mp, ma, ma - mp, rel, pnl / n * 100, t))
    print()
    print("解读: 差(pp) 为负=实际低于隐含(热门被高估); t 值 |t|>2 才算显著。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
