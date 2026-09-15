# -*- coding: utf-8 -*-
"""总进球低估的修法验证 —— 严格样本外: 前两季定校准, 后两季检验。

背景: tools/backtest_calibration.py 发现模型对大2.5/大3.5/BTTS 一致显著偏低
      (BTTS -3.84pp, t=-5.67), 指向 λ(预期进球)被压低。
修法: 对这两类概率做 logit 平移校准  logit(p') = logit(p) + a
      系数 a 只在前两个测试赛季上拟合, 再拿去后两个赛季检验。
判定: 配对 Brier 差的 t 值 < -2 才算"改完确实更好"。

用法: python tools/test_goals_fix.py
"""
import io, math, sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from models.dixon_coles import DixonColesModel
from pipeline.data_loader import load_all_csvs

FIVE = ("PL", "PD", "BL1", "SA", "FL1")
FIT_S = ("23-24", "24-25")     # 定校准系数
TEST_S = ("25-26", "26-27")    # 检验


def _logit(p, eps=1e-6):
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _sig(z):
    return 1.0 / (1.0 + math.exp(-z))


def collect():
    ms = [m for m in load_all_csvs() if m["league_code"] in FIVE and m.get("date")]
    ms.sort(key=lambda m: m["date"])
    rows = []
    for s in FIT_S + TEST_S:
        te = [m for m in ms if m["season"] == s]
        if not te:
            continue
        start = min(m["date"] for m in te)
        tr = [m for m in ms if m["date"] < start]
        dc = DixonColesModel()
        try:
            dc.fit_mle(tr)
        except Exception as e:
            print("  [%s] 拟合失败 %s" % (s, str(e)[:50]))
            continue
        n = 0
        for m in te:
            try:
                r = dc.predict(m["home_team"], m["away_team"], m["league_code"])
            except Exception:
                continue
            if not r or r.get("over_25") is None or r.get("btts") is None:
                continue
            h, a = m["home_goals"], m["away_goals"]
            rows.append((s, r["over_25"], 1.0 if h + a > 2.5 else 0.0,
                         r["btts"], 1.0 if (h > 0 and a > 0) else 0.0))
            n += 1
        print("  [%s] 测试 %d 场" % (s, n))
    return rows


def brier(p, y):
    return (p - y) ** 2


def main():
    rows = collect()
    fit = [r for r in rows if r[0] in FIT_S]
    test = [r for r in rows if r[0] in TEST_S]
    print()
    print("定系数集 %d 场 / 检验集 %d 场" % (len(fit), len(test)))
    if not fit or not test:
        return 1

    res = {}
    for name, i in (("大2.5", 1), ("双进球BTTS", 3)):
        best, ba = None, None
        for k in range(-100, 101):
            a = k * 0.01
            b = sum(brier(_sig(_logit(r[i]) + a), r[i + 1]) for r in fit) / len(fit)
            if best is None or b < best:
                best, ba = b, a
        # 检验
        d = []
        for r in test:
            p0 = r[i]
            p1 = _sig(_logit(p0) + ba)
            d.append(brier(p1, r[i + 1]) - brier(p0, r[i + 1]))
        n = len(d)
        mu = sum(d) / n
        sd = (sum((x - mu) ** 2 for x in d) / (n - 1)) ** 0.5
        se = sd / math.sqrt(n)
        t = mu / se if se else 0.0
        b0 = sum(brier(r[i], r[i + 1]) for r in test) / n
        b1 = sum(brier(_sig(_logit(r[i]) + ba), r[i + 1]) for r in test) / n
        res[name] = (ba, b0, b1, mu, t)
        v = "显著更优" if t < -2 else ("显著更差" if t > 2 else "不显著")
        print()
        print("%s:" % name)
        print("  拟合出的 logit 平移 a = %+.2f   (等价于整体概率上调)" % ba)
        print("  检验集 Brier: %.4f → %.4f" % (b0, b1))
        print("  配对差 %+.5f  标准误 %.5f  t = %.2f   %s" % (mu, se, t, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
