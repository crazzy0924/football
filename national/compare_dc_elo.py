# -*- coding: utf-8 -*-
"""DC vs Elo 对比工具 —— 两个已裁决的问题, 别再重复试。

用法:
    python national/compare_dc_elo.py            # 用缓存 (没有就跑一次回测)
    python national/compare_dc_elo.py --rerun    # 强制重跑回测

已裁决的两件事 (2026-09-24, 追查"挪威为什么被评低"时做的):

  Q1. 把 Elo 掺进 DC 会不会更好?
      -> 不会。目标口径(16强之间 n=270)上**纯 DC 最优** (0.61155);
         掺 Elo 反而更差 (DC权重0.5 时 0.61523, 配对 t=+0.78 不显著)。
         全量 826 场上最优权重 0.8, 但改善仅 0.00071, t=-0.62 不显著。

  Q2. DC 与 Elo 分歧时, 谁对? 该不该"分歧时改用 Elo"?
      -> DC 更准。分歧场次 n=120: DC 0.65397(命中40.0%) vs Elo 0.67484(命中29.2%);
         一致场次 n=706: DC 显著更好 (t=-2.36)。
         条件化(分歧时改用Elo) 全量 Brier 0.57471 vs 纯DC 0.57168 -> **更差** (t=+1.08)。

背景: 挪威被 DC 评低 (DC #16 vs 我们自己的 Elo #13 vs 市场暗示的更强),
      且 DC 轨迹显示它跟不上挪威的崛起 (挪威-丹麦 DC 差 -0.358 -> -0.040,
      同期 Elo 差 -80.6 -> +106.6)。但上面两条说明**赛果数据层面没有修法**。
      结论: 模型与市场分歧时, 没有证据表明我们对 -> 先验应该是"市场对"。
      (w=0.10 的依据之一, 见 docs/欧国联预测方案.md 第 8/9 节)
"""
import math, os, pickle, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _R not in sys.path:
    sys.path.insert(0, _R)
CACHE = os.path.join(_R, "national", "_dcelo_cache.pkl")


def build_cache():
    from datetime import date as _D
    from national.corpus import load_matches
    from national.dc_national import NationalDC
    from national.elo import (HOME_BONUS, K_BY_COMP, INITIAL, _g, _we, compute_elo,
                              fit_outcome_table, lookup)
    from national import ALL_A_TEAMS
    CUR_A = set(ALL_A_TEAMS)
    ALL = load_matches(since="2013-01-01")
    NL = [m for m in ALL if m["tournament"].startswith("UEFA Nations League")]
    EL = [m for m in ALL if m["home"] in CUR_A and m["away"] in CUR_A and m["date"] >= "2018-01-01"]
    seen = set(); T = []
    for m in NL + EL:
        k = (m["date"], m["home"], m["away"])
        if k in seen: continue
        seen.add(k); T.append(m)
    T.sort(key=lambda m: m["date"])
    dd = lambda s: _D(*[int(x) for x in s.split("-")])
    wins, cur = [], [T[0]]
    for prev, m in zip(T, T[1:]):
        if (dd(m["date"]) - dd(prev["date"])).days > 20: wins.append(cur); cur = [m]
        else: cur.append(m)
    wins.append(cur)
    print("回测 %d 场 / %d 个比赛窗 ..." % (len(T), len(wins)))
    recs = []
    t0 = time.time()
    for wi, win in enumerate(wins):
        start = win[0]["date"]
        train = [x for x in ALL if x["date"] < start]
        if len(train) < 3000: continue
        model = NationalDC(half_life_days=730.0, alpha_team=0.2).fit(train)
        rdict, pre = compute_elo(train)
        tbl = fit_outcome_table(train, pre)
        r2 = dict(rdict)
        for m in win:
            h, a = m["home"], m["away"]
            if h not in model.att or a not in model.att: continue
            k = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
            dcr = model.predict(h, a, neutral=m["neutral"], comp=m["comp"])
            bonus = 0.0 if m["neutral"] else HOME_BONUS
            rh, ra = r2.get(h, INITIAL), r2.get(a, INITIAL)
            diff = (rh + bonus) - ra
            recs.append({"k": k,
                         "dc": [dcr["home_win"], dcr["draw"], dcr["away_win"]],
                         "elo": lookup(tbl, diff),
                         "nl": m["tournament"].startswith("UEFA Nations League"),
                         "strong": (h in CUR_A and a in CUR_A)})
            we = _we(diff)
            w = 1.0 if k == 0 else (0.5 if k == 1 else 0.0)
            dl = K_BY_COMP.get(m["comp"], 40.0) * _g(m["hg"] - m["ag"]) * (w - we)
            r2[h] = rh + dl; r2[a] = ra - dl
        if (wi + 1) % 10 == 0:
            print("  窗 %d/%d (%.0fs)" % (wi + 1, len(wins), time.time() - t0))
    pickle.dump(recs, open(CACHE, "wb"))
    print("已缓存 -> %s" % os.path.basename(CACHE))
    return recs


def lp(pd, pe, w):
    out = []
    for x, y in zip(pd, pe):
        out.append(math.exp(w * math.log(max(x, 1e-9)) + (1 - w) * math.log(max(y, 1e-9))))
    s = sum(out)
    return [v / s for v in out]


def main():
    force = "--rerun" in sys.argv
    if force or not os.path.exists(CACHE):
        recs = build_cache()
    else:
        recs = pickle.load(open(CACHE, "rb"))
        print("用缓存 %d 场 (--rerun 可强制重跑)" % len(recs))
    print()

    def br(p, k):
        y = [0.0, 0.0, 0.0]; y[k] = 1.0
        return sum((p[i] - y[i]) ** 2 for i in range(3))
    def paired(ds):
        n = len(ds); mu = sum(ds) / n
        var = sum((d - mu) ** 2 for d in ds) / (n - 1)
        se = math.sqrt(var / n)
        return mu, se, (mu / se if se else 0)

    print("=" * 68)
    print("Q1. 把 Elo 掺进 DC 会不会更好?  (DC权重 1.0 = 纯 DC)")
    print("=" * 68)
    def sweep(sub, name):
        n = len(sub)
        if n < 30:
            print("  %s n=%d 太少" % (name, n)); return
        print("  %s  n=%d" % (name, n))
        print("     DC权重   Brier     命中率")
        res, best = {}, None
        for w in [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]:
            ps = [lp(x["dc"], x["elo"], w) for x in sub]
            bs = [br(p, x["k"]) for p, x in zip(ps, sub)]
            b = sum(bs) / n
            res[w] = bs
            hit = sum(1 for p, x in zip(ps, sub) if p.index(max(p)) == x["k"])
            mk = ""
            if best is None or b < best[0]: best = (b, w); mk = "  <-"
            print("     %.1f     %.5f   %5.1f%%%s" % (w, b, 100 * hit / n, mk))
        mu, se, t = paired([x - y for x, y in zip(res[best[1]], res[1.0])])
        print("     最优 DC权重 %.1f, 对纯DC: %+.5f se=%.5f t=%+.2f %s"
              % (best[1], mu, se, t, "显著" if abs(t) > 2 else "不显著"))
        print()
    sweep(recs, "全部")
    sweep([x for x in recs if x["strong"]], "16强之间 (目标口径)")
    sweep([x for x in recs if x["nl"]], "仅欧国联")

    print("=" * 68)
    print("Q2. DC 与 Elo 分歧时谁对?")
    print("=" * 68)
    for x in recs:
        x["bd"] = br(x["dc"], x["k"]); x["be"] = br(x["elo"], x["k"])
        x["disagree"] = x["dc"].index(max(x["dc"])) != x["elo"].index(max(x["elo"]))
    for sub, nm in [([x for x in recs if x["disagree"]], "分歧场次"),
                    ([x for x in recs if not x["disagree"]], "一致场次")]:
        n = len(sub)
        if n < 20: continue
        bd = sum(x["bd"] for x in sub) / n; be = sum(x["be"] for x in sub) / n
        hd = 100 * sum(1 for x in sub if x["dc"].index(max(x["dc"])) == x["k"]) / n
        he = 100 * sum(1 for x in sub if x["elo"].index(max(x["elo"])) == x["k"]) / n
        mu, se, t = paired([x["bd"] - x["be"] for x in sub])
        print("  %s n=%d:  DC %.5f(命中%.1f%%)  Elo %.5f(命中%.1f%%)  配对 t=%+.2f %s"
              % (nm, n, bd, hd, be, he, t, "显著" if abs(t) > 2 else "不显著"))
    cond = sum((x["be"] if x["disagree"] else x["bd"]) for x in recs) / len(recs)
    pure = sum(x["bd"] for x in recs) / len(recs)
    mu, se, t = paired([(x["be"] if x["disagree"] else x["bd"]) - x["bd"] for x in recs])
    print("  条件化(分歧时改用Elo): %.5f  vs 纯DC %.5f   配对 %+.5f t=%+.2f %s"
          % (cond, pure, mu, t, "显著" if abs(t) > 2 else "不显著"))
    print("  => 结论: 分歧时 DC 至少不差, 改用 Elo 更糟。没有基于赛果数据的修法。")


if __name__ == "__main__":
    main()