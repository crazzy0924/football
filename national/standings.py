# -*- coding: utf-8 -*-
"""欧国联 League A 小组形势 —— **纯展示层, 不进模型**。

为什么只做展示 (2026-09-24):
  战意/形势确实会影响比赛, 但**无法验证**: 四个赛季里真正"有分化"的场次
  (第 5/6 轮, 一方已定级) 加起来约 60 场, 而我们的功效测算显示要检出 Brier 差 0.02
  需要 933 场。所以把它塞进模型 = 塞一个无法证伪的假设, 违反"先验证再加"的纪律。

  它的正确用途:**当分歧预警触发时, 给人一个去看形势的入口**
  (见 docs/欧国联预测方案.md 第 9.1 节结论 3: 分歧时该查场外信息, 不是改模型)。

用法:
    python national/standings.py                  # 打印当前形势
    python national/standings.py --date 2026-10-05
"""
import argparse, os, sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from national import LEAGUE_A_2026_27  # noqa: E402
from national.corpus import load_matches  # noqa: E402

# 本届(2026/27)联赛阶段的起止。只统计这个区间内的比赛。
EDITION_START = "2026-09-20"
EDITION_END = "2026-11-30"
TOTAL_ROUNDS = 6


def empty_row():
    return {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}


def build_tables(matches: list[dict]) -> dict:
    """按小组统计。只吃本届联赛阶段、且双方都在 League A 的比赛。"""
    of = {t: g for g, ts in LEAGUE_A_2026_27.items() for t in ts}
    tables = {g: {t: empty_row() for t in ts} for g, ts in LEAGUE_A_2026_27.items()}
    for m in matches:
        h, a = m["home"], m["away"]
        if h not in of or a not in of or of[h] != of[a]:
            continue
        if not (EDITION_START <= m["date"] <= EDITION_END):
            continue
        g = of[h]
        rh, ra = tables[g][h], tables[g][a]
        rh["p"] += 1; ra["p"] += 1
        rh["gf"] += m["hg"]; rh["ga"] += m["ag"]
        ra["gf"] += m["ag"]; ra["ga"] += m["hg"]
        if m["hg"] > m["ag"]:
            rh["w"] += 1; ra["l"] += 1; rh["pts"] += 3
        elif m["hg"] == m["ag"]:
            rh["d"] += 1; ra["d"] += 1; rh["pts"] += 1; ra["pts"] += 1
        else:
            ra["w"] += 1; rh["l"] += 1; ra["pts"] += 3
    return tables


def rounds_played(table: dict) -> int:
    """已完成的轮次 = 各队已赛场次的**最小值** (保守: 只要有人没踢完就不算整轮)。"""
    return min((r["p"] for r in table.values()), default=0)


def stakes(table: dict) -> dict:
    """给每支队一个形势标签。出线 = 小组第一进 1/4 决赛; 垫底 = 降级。

    判定只用**可证明**的条件 (不含净胜球等平局条款, 保守):
      已锁定第一: 我的当前分 > 其他所有人的理论最高分
      已无缘第一: 我的理论最高分 < 其他所有人的当前分
      已锁定垫底: 我的理论最高分 < 其他所有人的当前分
      已避免垫底: 我的当前分 > 其他至少一人的理论最高分
    第 1 轮前所有条件都为假 -> 标签是「正常」, 这是对的。
    """
    rem = {t: max(0, TOTAL_ROUNDS - r["p"]) for t, r in table.items()}
    cur = {t: r["pts"] for t, r in table.items()}
    mx = {t: cur[t] + 3 * rem[t] for t in table}
    out = {}
    for t in table:
        others = [k for k in table if k != t]
        o_mx_max = max((mx[k] for k in others), default=0)   # 别人最高能到多少
        o_cur_max = max((cur[k] for k in others), default=0)  # 别人现在最多多少分
        o_cur_min = min((cur[k] for k in others), default=0)  # 别人现在最少多少分
        o_mx_min = min((mx[k] for k in others), default=0)   # 别人最低能到多少
        tags = []
        if rem[t] == 0 and all(rem[k] == 0 for k in others):
            tags.append("已定局")
        else:
            if cur[t] > o_mx_max:
                tags.append("已锁定第一")
            elif mx[t] < o_cur_max:
                tags.append("已无缘第一")
            if mx[t] < o_cur_min:
                tags.append("已锁定垫底")
            elif cur[t] > o_mx_min and "已锁定第一" not in tags:
                # 已经锁定第一时再说"已避免垫底"是废话, 去掉
                tags.append("已避免垫底")
        out[t] = {
            "played": table[t]["p"], "pts": cur[t],
            "gd": table[t]["gf"] - table[t]["ga"],
            "remaining": rem[t], "max_pts": mx[t], "tags": tags,
            "note": " / ".join(tags) if tags else "正常",
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    ms = load_matches(since=EDITION_START, until=EDITION_END)
    tables = build_tables(ms)
    played = 0
    if tables:
        played = max(rounds_played(t) for t in tables.values())
    print("=" * 70)
    print("2026/27 欧国联 League A 小组形势   (截至 %s)" % args.date)
    print("已完成轮次: %d / %d   联赛阶段区间 %s ~ %s" % (played, TOTAL_ROUNDS, EDITION_START, EDITION_END))
    print("=" * 70)
    for g in sorted(tables):
        tb = tables[g]
        st = stakes(tb)
        print()
        print("  [%s]" % g)
        print("     球队                 赛  胜 平 负   进  失   净   分   形势")
        order = sorted(tb, key=lambda t: (-tb[t]["pts"], -(tb[t]["gf"] - tb[t]["ga"])))
        for i, t in enumerate(order):
            r = tb[t]
            print("     %s %-18s %2d  %2d %2d %2d  %3d %3d  %+3d  %3d   %s"
                  % ("1." if i == 0 else ("4." if i == 3 else "  "), t,
                     r["p"], r["w"], r["d"], r["l"], r["gf"], r["ga"],
                     r["gf"] - r["ga"], r["pts"], st[t]["note"]))
    if played == 0:
        print()
        print("  (联赛阶段尚未开始/尚无赛果 —— 第 1-2 轮各队战意一致, 无分化。)")
    print()
    print("  说明: 本模块**只做展示, 不进模型**。理由见文件头注释与方案文档第 9.2 节。")


if __name__ == "__main__":
    main()