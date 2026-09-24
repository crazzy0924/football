# -*- coding: utf-8 -*-
"""欧国联专项滚动回测 —— 模拟真实生产: 每个比赛窗只用该窗之前的比赛训练。"""
import math, os, sys, time
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _R not in sys.path: sys.path.insert(0, _R)
from datetime import date as _D
from national.corpus import load_matches
from national.dc_national import NationalDC
from national.elo import HOME_BONUS, K_BY_COMP, INITIAL, _g, _we, compute_elo, fit_outcome_table, lookup
from national import ALL_A_TEAMS

CUR_A = set(ALL_A_TEAMS)
ALL = load_matches(since="2013-01-01")
NL = sorted([m for m in ALL if m["tournament"].startswith("UEFA Nations League")], key=lambda m: m["date"])
print("欧国联历史 %d 场, 语料 %d 场" % (len(NL), len(ALL)))

def dd(s): return _D(*[int(x) for x in s.split("-")])
windows, cur = [], [NL[0]]
for prev, m in zip(NL, NL[1:]):
    if (dd(m["date"]) - dd(prev["date"])).days > 20:
        windows.append(cur); cur = [m]
    else:
        cur.append(m)
windows.append(cur)
print("分成 %d 个比赛窗" % len(windows))
print()

ALPHA, HL = 0.2, 730.0
rows = []
t0 = time.time()
for wi, win in enumerate(windows):
    start = win[0]["date"]
    train = [m for m in ALL if m["date"] < start]
    if len(train) < 3000:
        continue
    model = NationalDC(half_life_days=HL, alpha_team=ALPHA).fit(train)
    rdict, pre = compute_elo(train)
    tbl = fit_outcome_table(train, pre)
    base = tbl["base"]
    r2 = dict(rdict)
    for m in win:
        h, a = m["home"], m["away"]
        if h not in model.att or a not in model.att:
            continue
        k = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
        dcr = model.predict(h, a, neutral=m["neutral"], comp=m["comp"])
        pd = [dcr["home_win"], dcr["draw"], dcr["away_win"]]
        bonus = 0.0 if m["neutral"] else HOME_BONUS
        rh, ra = r2.get(h, INITIAL), r2.get(a, INITIAL)
        diff = (rh + bonus) - ra
        pe = lookup(tbl, diff)
        y = [0.0, 0.0, 0.0]; y[k] = 1.0
        br = lambda p: sum((p[i]-y[i])**2 for i in range(3))
        rows.append({"date": m["date"], "home": h, "away": a, "k": k,
                     "dc": br(pd), "elo": br(pe), "base": br(base),
                     "hit_dc": pd.index(max(pd)) == k, "hit_elo": pe.index(max(pe)) == k,
                     "hit_base": base.index(max(base)) == k,
                     "top_dc": max(pd), "strong": (h in CUR_A and a in CUR_A)})
        we = _we(diff)
        w = 1.0 if k == 0 else (0.5 if k == 1 else 0.0)
        dl = K_BY_COMP.get(m["comp"], 40.0) * _g(m["hg"] - m["ag"]) * (w - we)
        r2[h] = rh + dl; r2[a] = ra - dl
    print("  窗 %2d/%d  %s  %2d 场  训练 %5d  (%.0fs)" % (wi+1, len(windows), start, len(win), len(train), time.time()-t0))

print()
def paired(ds):
    n = len(ds); mu = sum(ds)/n
    var = sum((d-mu)**2 for d in ds)/(n-1)
    se = math.sqrt(var/n)
    return mu, se, (mu/se if se else 0)
def rep(sub, name):
    n = len(sub)
    if n < 20:
        print("  %s  n=%d (太少, 不下结论)" % (name, n)); return
    print("  %s   n=%d" % (name, n))
    print("     DC       Brier %.5f   命中 %.1f%%" % (sum(x["dc"] for x in sub)/n, 100*sum(1 for x in sub if x["hit_dc"])/n))
    print("     Elo      Brier %.5f   命中 %.1f%%" % (sum(x["elo"] for x in sub)/n, 100*sum(1 for x in sub if x["hit_elo"])/n))
    print("     基准     Brier %.5f   命中 %.1f%%" % (sum(x["base"] for x in sub)/n, 100*sum(1 for x in sub if x["hit_base"])/n))
    for k2, nm in [("elo", "DC-Elo"), ("base", "DC-基准")]:
        mu, se, t = paired([x["dc"]-x[k2] for x in sub])
        print("     配对 %-10s %+.5f  se=%.5f  t=%+.2f  %s" % (nm, mu, se, t, "显著" if abs(t) > 2 else "不显著"))
    print()
print("--- 全部欧国联 ---")
rep(rows, "全部欧国联")
print("--- 双方都在当前 League A 16 队内 (目标口径) ---")
rep([x for x in rows if x["strong"]], "双方均为 League A")
print("总回测场次 %d" % len(rows))