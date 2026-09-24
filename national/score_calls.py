# -*- coding: utf-8 -*-
"""判断台账打分器 —— 台账没有它就是一叠摆设。

判据 (2026-09-24 用户拍板):
  **主判据 = 只考核「反向」场次。**
  同向场次我们只是在附和市场, 没有信息量 —— 在那里赢市场不算本事, 输市场也不丢人。
  只有"我们和市场反着来"的场次, 才是这套方法真正在下注。每季约 16 场。

  ⚠️ 因此**显著性永远拿不到** (League A 每年只新增 48 场, 检出 0.02 的效应要 933 场)。
     这套方法的价值不能靠 p 值证明, 只能靠长期台账给人看。

两条对照轨一起打:
  A 轨 `octa.py`    情报 + 独立判断 (台账 calls_ledger.jsonl, 取每场 revision 最大的一条)
  B 轨 `run_nl.py`  纯数据 + DC + 市场融合 w=0.10 (predictions_nl_<date>.json)

用法: python national/score_calls.py [--date 2026-09-24]
"""
import argparse, glob, json, os, sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

LEDGER = os.path.join(_ROOT, "data", "national", "calls_ledger.jsonl")


def load_latest_calls() -> list[dict]:
    """台账只追加不修改, 所以同一场会有多个 revision。**只取最大的那条**。"""
    if not os.path.exists(LEDGER):
        return []
    best: dict[tuple, dict] = {}
    with open(LEDGER, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = (r.get("business_date"), r.get("home"), r.get("away"))
            if k not in best or int(r.get("revision", 0) or 0) > int(best[k].get("revision", 0) or 0):
                best[k] = r
    return list(best.values())


def load_results() -> dict[tuple, tuple]:
    """从语料里读赛果, 建 (日期, 主, 客) -> (主进球, 客进球)。"""
    from national.corpus import load_matches
    out = {}
    for m in load_matches(since="2026-09-01"):
        out[(m["date"], m["home"], m["away"])] = (m["hg"], m["ag"])
    return out


def find_result(results: dict, date_str: str, home: str, away: str):
    """容忍 ±1 天: 语料记的是当地日期, 体彩记的是比赛日, 欧洲晚场两者一致, 但别赌。"""
    from datetime import date as _D, timedelta
    y, mo, d = [int(x) for x in date_str.split("-")]
    for delta in (0, 1, -1):
        k = ((_D(y, mo, d) + timedelta(days=delta)).isoformat(), home, away)
        if k in results:
            return results[k]
    return None


def actual_side(hg: int, ag: int) -> str:
    return "主胜" if hg > ag else ("平局" if hg == ag else "客胜")


def market_pick(mp: dict) -> str:
    if not mp:
        return "?"
    ks = ["home", "draw", "away"]
    i = max(range(3), key=lambda j: mp.get(ks[j], 0))
    return ["主胜", "平局", "客胜"][i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    args = ap.parse_args()

    calls = load_latest_calls()
    if args.date:
        calls = [c for c in calls if c.get("business_date") == args.date]
    if not calls:
        print("台账里没有匹配的记录")
        return 1
    results = load_results()

    scored, pending = [], []
    for c in calls:
        r = find_result(results, c.get("business_date", ""), c.get("home", ""), c.get("away", ""))
        if r is None:
            pending.append(c)
            continue
        hg, ag = r
        act = actual_side(hg, ag)
        f = c.get("final") or {}
        s2 = c.get("stage2_vs_market") or {}
        mp = c.get("market_probs") or {}
        ours = f.get("站边") or (c.get("stage1_blind") or {}).get("站边")
        mkt = market_pick(mp)
        scored.append({
            "tag": "%s vs %s" % (c.get("home_cn"), c.get("away_cn")),
            "date": c.get("business_date"), "score": "%d-%d" % (hg, ag), "actual": act,
            "ours": ours, "market": mkt,
            "ours_hit": ours == act, "market_hit": mkt == act,
            "score_hit": str(f.get("比分") or "").replace(" ", "") == "%d-%d" % (hg, ag),
            "relation": s2.get("市场与我的关系", "?"),
            "agree_rate": f.get("自洽度") or (c.get("stage1_blind") or {}).get("_一致度") or "?",
            "conf": f.get("置信度分"),
            "diverged": (s2.get("市场与我的关系") == "反向"),
        })

    print("=" * 74)
    print("八维盲判台账打分   %d 场已结算 / %d 场待结算" % (len(scored), len(pending)))
    print("=" * 74)
    if pending:
        for c in pending:
            print("   待结算: %s vs %s (%s)  —— 赛果还没进语料, 先跑 refresh_corpus.py"
                  % (c.get("home_cn"), c.get("away_cn"), c.get("business_date")))
        print()
    if not scored:
        print("   还没有可结算的场次。等赛果进语料后再跑。")
        return 0

    print("   %-22s %-6s %-5s %-5s %-5s %-4s %-5s %s"
          % ("场次", "比分", "实际", "我们", "市场", "关系", "自洽", "中?"))
    for s in scored:
        print("   %-22s %-6s %-5s %-5s %-5s %-4s %-5s %s%s"
              % (s["tag"][:22], s["score"], s["actual"], s["ours"], s["market"],
                 s["relation"], s["agree_rate"], "✔" if s["ours_hit"] else "✘",
                 "  (比分也中)" if s["score_hit"] else ""))
    print()

    def rate(sub, key):
        return (100.0 * sum(1 for x in sub if x[key]) / len(sub)) if sub else 0.0

    div = [s for s in scored if s["diverged"]]
    same = [s for s in scored if not s["diverged"]]
    print("   === 主判据: 反向场次 (我们真正在下注的地方) ===")
    if div:
        print("      n=%d   我们命中 %.1f%%   市场命中 %.1f%%   比分命中 %.1f%%"
              % (len(div), rate(div, "ours_hit"), rate(div, "market_hit"), rate(div, "score_hit")))
    else:
        print("      本轮没有反向场次")
    print("   === 参考: 同向场次 (只是在附和市场, 不计入判据) ===")
    if same:
        print("      n=%d   我们命中 %.1f%%   市场命中 %.1f%%"
              % (len(same), rate(same, "ours_hit"), rate(same, "market_hit")))
    print()
    print("   === 全部场次 ===")
    print("      n=%d   我们命中 %.1f%%   市场命中 %.1f%%   比分命中 %.1f%%"
          % (len(scored), rate(scored, "ours_hit"), rate(scored, "market_hit"),
             rate(scored, "score_hit")))
    # 自洽度是否预测准确率 —— 这是自洽投票到底有没有意义的检验
    for lvl in ("3/3", "2/3", "1/3"):
        sub = [s for s in scored if s["agree_rate"] == lvl]
        if sub:
            print("      自洽度 %s: n=%d  命中 %.1f%%" % (lvl, len(sub), rate(sub, "ours_hit")))
    print()
    print("   ⚠ 样本极小, 单轮数字没有统计意义。判据要跨赛季累积。")

    # B 轨对照
    print()
    print("=" * 74)
    print("B 轨对照 (run_nl.py: DC + 市场融合 w=0.10)")
    for f in sorted(glob.glob(os.path.join(_ROOT, "data", "national", "predictions_nl_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        n = hit = 0
        for m in d.get("matches", []):
            r = find_result(results, m.get("business_date", ""), m.get("home", ""), m.get("away", ""))
            if r is None or not m.get("fused"):
                continue
            act = actual_side(*r)
            fu = m["fused"]
            pick = ["主胜", "平局", "客胜"][max(range(3), key=lambda i: fu[["home", "draw", "away"][i]])]
            n += 1
            hit += 1 if pick == act else 0
        if n:
            print("   %s   n=%d  B轨命中 %.1f%%" % (os.path.basename(f), n, 100.0 * hit / n))
    print("   (B 轨没有 A 轨的「反向」概念 —— 它本质上是市场的复述, 所以没有独立判据。)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())