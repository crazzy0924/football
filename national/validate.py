# -*- coding: utf-8 -*-
"""国家队模型的样本外验证 —— 沿用俱乐部的配对检验纪律。

口径:
  - 留出法: 训练 = 截至 SPLIT 之前, 测试 = SPLIT 之后 (严格不重叠)
  - Elo 与 Elo->1X2 映射表都只在训练集上拟合
  - 指标: 多分类 Brier (越小越好) + 命中率
  - 配对检验: 逐场 Brier 差的均值 / 标准误 / t 值, |t|>2 才算显著
"""
import math, os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from national.corpus import load_matches
from national.dc_national import NationalDC
from national.elo import compute_elo, fit_outcome_table, lookup


def brier(p, k):
    y = [0.0, 0.0, 0.0]
    y[k] = 1.0
    return sum((p[i] - y[i]) ** 2 for i in range(3))


def paired(diffs):
    n = len(diffs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mu = sum(diffs) / n
    var = sum((d - mu) ** 2 for d in diffs) / (n - 1)
    se = math.sqrt(var / n)
    return mu, se, (mu / se if se > 0 else 0.0)


def run(split: str = "2025-09-24", alpha: float = 1.0, half_life: float = 730.0,
        scope=None, label: str = "全部国际比赛"):
    allm = load_matches(since="2016-01-01")
    tr = [m for m in allm if m["date"] < split]
    te = [m for m in allm if m["date"] >= split]
    if scope:
        tr = [m for m in tr if scope(m)]
        te = [m for m in te if scope(m)]

    m = NationalDC(half_life_days=half_life, alpha_team=alpha).fit(tr)
    r, pre_tr = compute_elo(tr)
    tbl = fit_outcome_table(tr, pre_tr)

    base = tbl["base"]
    res = {"dc": [], "elo": [], "base": []}
    hits = {"dc": 0, "elo": 0, "base": 0}
    # 测试集 Elo 需要延续训练结束时的评分
    r2 = dict(r)
    from national.elo import HOME_BONUS, K_BY_COMP, _g, _we
    for mm in te:
        h, a = mm["home"], mm["away"]
        if h not in m.att or a not in m.att:
            continue
        bonus = 0.0 if mm["neutral"] else HOME_BONUS
        rh, ra = r2.get(h, 1500.0), r2.get(a, 1500.0)
        diff = (rh + bonus) - ra
        k = 0 if mm["hg"] > mm["ag"] else (1 if mm["hg"] == mm["ag"] else 2)
        dc = m.predict(h, a, neutral=mm["neutral"], comp=mm["comp"])
        pd = [dc["home_win"], dc["draw"], dc["away_win"]]
        pe = lookup(tbl, diff)
        bs = [brier(pd, k), brier(pe, k), brier(base, k)]
        for i, key in enumerate(["dc", "elo", "base"]):
            res[key].append(bs[i])
            if max([pd, pe, base][i]) == [pd, pe, base][i][k]:
                pass
        if pd.index(max(pd)) == k:
            hits["dc"] += 1
        if pe.index(max(pe)) == k:
            hits["elo"] += 1
        if base.index(max(base)) == k:
            hits["base"] += 1
        # 滚动更新 Elo
        we = _we(diff)
        w = 1.0 if k == 0 else (0.5 if k == 1 else 0.0)
        d = K_BY_COMP.get(mm["comp"], 40.0) * _g(mm["hg"] - mm["ag"]) * (w - we)
        r2[h] = rh + d
        r2[a] = ra - d

    n = len(res["dc"])
    if n == 0:
        print("  %s: 测试集为空" % label)
        return
    print("  %s   训练 %d 场 / 测试 %d 场 (%s 起)" % (label, len(tr), n, split))
    print("     模型          Brier     命中率")
    for key, nm in [("dc", "DC(独立国家队)"), ("elo", "Elo+分桶映射"), ("base", "基准(全训练集频率)")]:
        b = sum(res[key]) / n
        print("     %-16s %.5f   %5.1f%%  (%d/%d)" % (nm, b, 100.0 * hits[key] / n, hits[key], n))
    d1 = [res["dc"][i] - res["elo"][i] for i in range(n)]
    mu, se, t = paired(d1)
    print("     配对 DC - Elo      : %+.5f  se=%.5f  t=%+.2f  %s" % (mu, se, t, "显著" if abs(t) > 2 else "不显著"))
    d2 = [res["dc"][i] - res["base"][i] for i in range(n)]
    mu, se, t = paired(d2)
    print("     配对 DC - 基准     : %+.5f  se=%.5f  t=%+.2f  %s" % (mu, se, t, "显著" if abs(t) > 2 else "不显著"))
    return res


if __name__ == "__main__":
    print("=== 国家队模型留出验证 (split=2025-09-24) ===")
    run()