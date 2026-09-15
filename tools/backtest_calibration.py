# -*- coding: utf-8 -*-
"""维度校准偏差检验 —— 回答"模型是不是系统性偏高/偏低"。

背景 (2026-09-15, 来自假设台账 hypothesis_ledger):
  复盘归因里反复出现两条:
    - "模型仍把最低比分 1-0 列为最高概率" (波胆/比分, 25 天 202 条)
    - "模型 BTTS 57% 过高" (大小球/波胆)
  这两条说的是"系统性偏高", 而系统性偏差是可以量化的:
     偏差 = 预测概率均值 - 实际发生率
     配对 t 检验: d_i = p_i - 实际(0/1), t = mean(d)/se(d)

判定: |t| > 2 才算真偏差; 否则记为"证据不足, 不立项"。
注意: 这只是"发现问题"。真要改模型, 还得再跑一次配对检验证明改完更好。

用法: python tools/backtest_calibration.py
"""
import io, sys, math
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from models.dixon_coles import DixonColesModel
from pipeline.data_loader import load_all_csvs

FIVE = ("PL", "PD", "BL1", "SA", "FL1")
TESTS = ("23-24", "24-25", "25-26", "26-27")


def main():
    ms = [m for m in load_all_csvs() if m["league_code"] in FIVE and m.get("date")]
    ms.sort(key=lambda m: m["date"])
    dims = {"大2.5": [], "大3.5": [], "双进球BTTS": [], "最低比分占比": []}
    n_top = n_top_low = n_top_hit = 0
    lowset = {"0-0", "1-0", "0-1", "1-1"}
    for s in TESTS:
        te = [m for m in ms if m["season"] == s]
        if not te:
            continue
        start = min(m["date"] for m in te)
        tr = [m for m in ms if m["date"] < start]
        if not tr:
            continue
        dc = DixonColesModel()
        try:
            dc.fit_mle(tr)
        except Exception as e:
            print("  [%s] 拟合失败: %s" % (s, str(e)[:60]))
            continue
        cnt = 0
        for m in te:
            try:
                r = dc.predict(m["home_team"], m["away_team"], m["league_code"])
            except Exception:
                continue
            if not r or r.get("over_25") is None:
                continue
            h, a = m["home_goals"], m["away_goals"]
            tot = h + a
            dims["大2.5"].append((r["over_25"], 1.0 if tot > 2.5 else 0.0))
            if r.get("over_35") is not None:
                dims["大3.5"].append((r["over_35"], 1.0 if tot > 3.5 else 0.0))
            if r.get("btts") is not None:
                dims["双进球BTTS"].append((r["btts"], 1.0 if (h > 0 and a > 0) else 0.0))
            sd = r.get("score_distribution") or {}
            if sd:
                top = max(sd.items(), key=lambda kv: kv[1])[0]
                n_top += 1
                n_top_low += (top in lowset)
                n_top_hit += (top == "%d-%d" % (h, a))
            cnt += 1
        print("  [%s] 训练 %d / 测试 %d 场" % (s, len(tr), cnt))

    print()
    print("=" * 76)
    print("维度校准偏差: 预测概率均值 - 实际发生率  (正=模型偏高)")
    print("=" * 76)
    hdr = "%-14s %-9s %-11s %-11s %-10s %-8s %s" % (
        "维度", "场次", "预测均值", "实际发生", "偏差", "t 值", "结论")
    print(hdr)
    print("-" * len(hdr))
    for k, arr in dims.items():
        if len(arr) < 50:
            continue
        n = len(arr)
        mp = sum(x[0] for x in arr) / n
        ma = sum(x[1] for x in arr) / n
        d = [arr[i][0] - arr[i][1] for i in range(n)]
        mu = sum(d) / n
        sd = (sum((x - mu) ** 2 for x in d) / (n - 1)) ** 0.5
        se = sd / math.sqrt(n) if n else 0
        t = mu / se if se else 0.0
        v = "显著偏高" if t > 2 else ("显著偏低" if t < -2 else "无显著偏差")
        print("%-14s %-9d %-11.4f %-11.4f %+.4f  %-8.2f %s" % (
            k, n, mp, ma, mu, t, v))
    print()
    if n_top:
        print("波胆最高概率比分: 共 %d 场" % n_top)
        print("  落在最低比分(0-0/1-0/0-1/1-1)的比例: %.1f%%" % (n_top_low / n_top * 100))
        print("  直接命中实际比分的比例: %.1f%%  (随机基准约 9~11%%)" % (n_top_hit / n_top * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
