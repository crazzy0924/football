# -*- coding: utf-8 -*-
"""配对检验: 把 xG 引入 Dixon-Coles 到底有没有用。

实验设计 (关键: 两臂只差一个变量)
  同一批训练数据、同一个拟合器、同一批测试比赛, 唯一差别是**拟合目标**:
      w=0   用实际进球拟合 (= 现版)
      w>0   用 有效进球 = w*xG + (1-w)*实际进球 拟合
  这样"xG 有没有用"就被隔离出来了, 不会被别的差异污染。

为什么不需要改生产代码:
  fit_mle 只读 match 字典里的 home_goals / away_goals。把这两个字段换成融合值,
  现有拟合器原样可用 —— 不新增分支、不碰线上路径。

判定标准 (见 docs/xG接入评估计划.md, 不放宽):
  逐场 Brier 差 (配对) 的 t 值绝对值 > 2 才算成立; 分联赛单独看。

用法:
    python tools/paired_xg_test.py
    python tools/paired_xg_test.py --w 0,0.5,1.0 --leagues PL,PD
"""
import argparse
import glob
import io
import json
import math
import os
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from models.dixon_coles import DixonColesModel  # noqa: E402
from pipeline.data_loader import load_all_csvs  # noqa: E402
from pipeline.team_names import canonical_of as C  # noqa: E402

FIVE = ("PL", "PD", "BL1", "SA", "FL1")
TEST_SEASONS = ("23-24", "24-25", "25-26", "26-27")


def _k(name: str) -> str:
    """配对键。规范名优先, 查不到就退回原名小写 —— 否则不在总表里的球队
    (升班马、已降级队) 会被整条丢掉, 配对率静默下降。"""
    return C(name) or (name or "").strip().lower()


def load_xg() -> dict:
    """(赛季, 主队键, 客队键) → (xg_h, xg_a)"""
    out = {}
    for f in glob.glob(os.path.join("data", "state", "xg", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        s = d.get("season")
        for v in (d.get("matches") or {}).values():
            if v.get("xg_h") is None or v.get("xg_a") is None:
                continue
            h, a = _k(v.get("home") or ""), _k(v.get("away") or "")
            if not h or not a:
                continue
            out[(s, h, a)] = (float(v["xg_h"]), float(v["xg_a"]))
    return out


def brier(p, act):
    k = "HDA".index(act)
    o = [1.0 if i == k else 0.0 for i in range(3)]
    return sum((p[i] - o[i]) ** 2 for i in range(3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", default="0,0.3,0.5,0.7,1.0", help="xG 融合权重网格")
    ap.add_argument("--leagues", default=",".join(FIVE))
    ap.add_argument("--seasons", default=",".join(TEST_SEASONS))
    a = ap.parse_args()
    ws = [float(x) for x in a.w.split(",") if x.strip()]
    keep = {x.strip().upper() for x in a.leagues.split(",") if x.strip()}
    tests = [x.strip() for x in a.seasons.split(",") if x.strip()]

    ms = [m for m in load_all_csvs()
          if m["league_code"] in keep and m.get("date") and m.get("season")]
    ms.sort(key=lambda m: m["date"])
    xg = load_xg()
    print("语料 %d 场 (%s) | xG 表 %d 条" % (len(ms), ",".join(sorted(keep)), len(xg)))

    # 配对率核对
    hit = 0
    for m in ms:
        if (m["season"], _k(m["home_team"]), _k(m["away_team"])) in xg:
            hit += 1
    print("xG 配对成功 %d/%d (%.1f%%)  ← 配对率过低会让样本静默变少" % (
        hit, len(ms), hit / max(len(ms), 1) * 100))
    print()

    per_w = {w: [] for w in ws}          # 每臂: [(brier, 联赛, 赛季)]
    for s in tests:
        te = [m for m in ms if m["season"] == s]
        if not te:
            continue
        start = min(m["date"] for m in te)
        tr = [m for m in ms if m["date"] < start]
        if not tr or not te:
            continue
        for w in ws:
            tr2 = []
            nblend = 0
            for m in tr:
                mm = dict(m)
                g = xg.get((m["season"], _k(m["home_team"]), _k(m["away_team"])))
                if w > 0 and g:
                    mm["home_goals"] = w * g[0] + (1 - w) * m["home_goals"]
                    mm["away_goals"] = w * g[1] + (1 - w) * m["away_goals"]
                    nblend += 1
                tr2.append(mm)
            dc = DixonColesModel()
            try:
                dc.fit_mle(tr2)
            except Exception as e:
                print("  [%s w=%.1f] 拟合失败: %s" % (s, w, str(e)[:70]))
                continue
            for m in te:
                try:
                    r = dc.predict(m["home_team"], m["away_team"], m["league_code"])
                except Exception:
                    continue
                if not r or r.get("home_win") is None:
                    continue
                p = [r["home_win"], r["draw"], r["away_win"]]
                h, g2 = m["home_goals"], m["away_goals"]
                act = "H" if h > g2 else ("D" if h == g2 else "A")
                per_w[w].append((brier(p, act), m["league_code"], s))
            print("  [%s] w=%.1f 训练 %d 场(融合 %d) / 测试 %d 场" % (
                s, w, len(tr2), nblend, len(te)))

    if 0.0 not in per_w or not per_w[0.0]:
        print("缺少基线 w=0，无法配对")
        return 1
    base = per_w[0.0]
    print()
    print("=" * 78)
    print("配对检验: 逐场 Brier 差 (配对) | 负值 = 引入 xG 更好")
    print("=" * 78)
    hdr = "%-7s %-8s %-11s %-10s %-9s %-14s %s" % ("w", "测试场次", "平均差", "标准误", "t 值", "95%区间", "结论")
    print(hdr)
    print("-" * len(hdr))
    for w in ws:
        cur = per_w[w]
        if len(cur) != len(base):
            print("%-7.1f 场次不一致, 跳过" % w)
            continue
        d = [cur[i][0] - base[i][0] for i in range(len(base))]
        n = len(d)
        mu = sum(d) / n
        sd = (sum((x - mu) ** 2 for x in d) / (n - 1)) ** 0.5 if n > 1 else 0.0
        se = sd / math.sqrt(n) if n else 0.0
        t = mu / se if se else 0.0
        lo, hi = mu - 1.96 * se, mu + 1.96 * se
        verdict = "显著更优" if t < -2 else ("显著更差" if t > 2 else "不显著")
        print("%-7.1f %-8d %+.5f   %-10.5f %-9.2f [%+.5f,%+.5f] %s" % (
            w, n, mu, se, t, lo, hi, verdict))
    # 用事先定好的 w=0.5 做拆分 (不挑"最好看的那一档", 避免选择偏差)
    W = 0.5 if 0.5 in per_w and len(per_w[0.5]) == len(base) else None
    if W is not None:
        cur = per_w[W]
        for tag, idx in (("分赛季", 2), ("分联赛", 1)):
            print()
            print("%s (固定在事先选定的 w=0.5, 不挑最好看的那档):" % tag)
            by = {}
            for i in range(len(base)):
                by.setdefault(cur[i][idx], []).append(cur[i][0] - base[i][0])
            for k in sorted(by):
                dd = by[k]
                if len(dd) < 40:
                    continue
                mm = sum(dd) / len(dd)
                ss = (sum((x - mm) ** 2 for x in dd) / (len(dd) - 1)) ** 0.5 / math.sqrt(len(dd))
                t = mm / ss if ss else 0.0
                print("  %-6s n=%-5d 差=%+.5f  se=%.5f  t=%-6.2f %s" % (
                    k, len(dd), mm, ss, t, "显著" if abs(t) > 2 else "不显著"))

    # 量纲核对: 融合会不会把整体进球水平挪走 (挪了就不是"换标签"而是"换尺度")
    print()
    print("量纲核对 (xG 均值 vs 进球均值):")
    for s in tests:
        gm = [m for m in ms if m["season"] == s]
        gh = [m["home_goals"] + m["away_goals"] for m in gm]
        xs = [xg[(m["season"], _k(m["home_team"]), _k(m["away_team"]))]
              for m in gm if (m["season"], _k(m["home_team"]), _k(m["away_team"])) in xg]
        if not gh or not xs:
            continue
        print("  %s  进球 %.3f  xG %.3f  差 %+.3f  (配对 %d/%d)" % (
            s, sum(gh) / len(gh), sum(a + b for a, b in xs) / len(xs),
            sum(a + b for a, b in xs) / len(xs) - sum(gh) / len(gh), len(xs), len(gm)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
