# -*- coding: utf-8 -*-
"""16 强之间的一切对话 (不限欧国联): 样本量够不够证明模型有技能?"""
import math, os, sys, time, collections
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
EL = sorted([m for m in ALL if m["home"] in CUR_A and m["away"] in CUR_A and m["date"] >= "2018-01-01"], key=lambda m: m["date"])
print("16 强之间的比赛 (2018 起, 全部赛事): %d 场" % len(EL))
for k, v in collections.Counter(m["comp"] for m in EL).most_common():
    print("   %-10s %3d" % (k, v))
print()
def dd(s): return _D(*[int(x) for x in s.split("-")])
windows, cur = [], [EL[0]]
for prev, m in zip(EL, EL[1:]):
    if (dd(m["date"]) - dd(prev["date"])).days > 20: windows.append(cur); cur=[m]
    else: cur.append(m)
windows.append(cur)
print("分成 %d 个比赛窗" % len(windows))
print()
ALPHA, HL = 0.2, 730.0
rows = []
t0 = time.time()
for win in windows:
    start = win[0]["date"]
    train = [m for m in ALL if m["date"] < start]
    if len(train) < 3000: continue
    model = NationalDC(half_life_days=HL, alpha_team=ALPHA).fit(train)
    rdict, pre = compute_elo(train)
    tbl = fit_outcome_table(train, pre)
    base = tbl["base"]
    r2 = dict(rdict)
    for m in win:
        h, a = m["home"], m["away"]
        if h not in model.att or a not in model.att: continue
        k = 0 if m["hg"]>m["ag"] else (1 if m["hg"]==m["ag"] else 2)
        dcr = model.predict(h, a, neutral=m["neutral"], comp=m["comp"])
        pd = [dcr["home_win"], dcr["draw"], dcr["away_win"]]
        bonus = 0.0 if m["neutral"] else HOME_BONUS
        rh, ra = r2.get(h, INITIAL), r2.get(a, INITIAL)
        diff = (rh + bonus) - ra
        pe = lookup(tbl, diff)
        y = [0.0,0.0,0.0]; y[k] = 1.0
        br = lambda p: sum((p[i]-y[i])**2 for i in range(3))
        rows.append({"comp": m["comp"], "nl": m["tournament"].startswith("UEFA Nations League"),
                     "dc": br(pd), "elo": br(pe), "base": br(base), "_k": k,
                     "hit_dc": pd.index(max(pd))==k, "hit_elo": pe.index(max(pe))==k,
                     "hit_base": base.index(max(base))==k})
        we = _we(diff)
        w = 1.0 if k==0 else (0.5 if k==1 else 0.0)
        dl = K_BY_COMP.get(m["comp"], 40.0) * _g(m["hg"]-m["ag"]) * (w-we)
        r2[h] = rh + dl; r2[a] = ra - dl
print("回测完成 %d 场, 耗时 %.0fs" % (len(rows), time.time()-t0))
print()
def paired(ds):
    n=len(ds); mu=sum(ds)/n
    var=sum((d-mu)**2 for d in ds)/(n-1); se=math.sqrt(var/n)
    return mu, se, (mu/se if se else 0)
def rep(sub, name):
    n=len(sub)
    if n < 20: print("  %-26s n=%d (太少)" % (name, n)); return
    dc = sum(x["dc"] for x in sub)/n; el = sum(x["elo"] for x in sub)/n; ba = sum(x["base"] for x in sub)/n
    uni = 0.66667
    print("  %-26s n=%-4d  DC %.5f | Elo %.5f | 基准 %.5f | 无技能 0.66667" % (name, n, dc, el, ba))
    print("       命中 DC %5.1f%%  Elo %5.1f%%    DC 相对无技能改善 %+.1f%%" % (100*sum(1 for x in sub if x["hit_dc"])/n, 100*sum(1 for x in sub if x["hit_elo"])/n, 100*(uni-dc)/uni))
    for k2, nm in [("elo","Elo"), ("base","基准")]:
        mu, se, t = paired([x["dc"]-x[k2] for x in sub])
        print("       配对 DC-%-6s %+.5f  se=%.5f  t=%+.2f  %s" % (nm, mu, se, t, "显著" if abs(t)>2 else "不显著"))
    print()
print("=== 16 强之间 (全部赛事, 2018+) ===")
rep(rows, "全部")
rep([x for x in rows if x["nl"]], "仅欧国联")
rep([x for x in rows if x["comp"]=="FINALS"], "仅决赛圈(欧洲杯/世界杯)")
rep([x for x in rows if x["comp"]=="QUAL"], "仅预选赛")
rep([x for x in rows if x["comp"]=="FRIENDLY"], "仅友谊赛")
print("--- 样本量需求: 要证明模型 vs 市场, 需要多少场? ---")
n=len(rows)
sd = math.sqrt(sum((x["dc"]-sum(y["dc"] for y in rows)/n)**2 for x in rows)/(n-1))
for effect in [0.005, 0.010, 0.020]:
    need = (2.0*sd/effect)**2
    print("   要检出 Brier 差 %.3f (t=2): 需要 %.0f 场" % (effect, need))
print("   当前 16 强样本 %d 场, 欧国联联赛阶段每年新增 48 场" % n)