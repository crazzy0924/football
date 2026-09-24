# -*- coding: utf-8 -*-
"""八维判读的自检 —— 每次跑完 octa.py 必须过一遍。

检查项:
  C1 七维恰好 7 项, 顺序固定, 权重合计 = 100
  C2 方向分 == Σ(优势分×权重)÷100  (容差 0.15, 允许四舍五入)
  C3 站边方向与方向分符号一致 (+利主 / -利客 / |.|<0.3 允许平)
  C4 最终比分的方向与站边一致 (主胜必须主>客, 客胜必须主<客, 平局必须相等)
  C5 置信度分必须有区分度 (跨场次检查) —— 全一样说明没有区分度
  C6 反编造: 七维证据里的日期必须能在证据包里找到; 情报写「未获取」时不许出现伤停断言
用法: python national/check_calls.py [--date 2026-09-24]
"""
import argparse, json, os, re, sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = ["状态攻防", "阵容伤停", "交锋克制", "赛程体能", "天气场地", "裁判", "战意轮换"]


def side_of(score: str) -> str | None:
    m = re.match(r"^\s*(\d+)\s*[-:：]\s*(\d+)\s*$", str(score or ""))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return "主胜" if a > b else ("平局" if a == b else "客胜")


def check(rec: dict, issues: list, warns: list) -> None:
    tag = "%s vs %s" % (rec.get("home_cn"), rec.get("away_cn"))
    s1 = rec.get("stage1_blind") or {}
    dims = s1.get("七维") or []
    # C1
    names = [d.get("维度") for d in dims]
    if names != ORDER:
        issues.append("%s C1 七维顺序/数量不对: %s" % (tag, names))
    try:
        wsum = sum(int(d.get("权重", 0)) for d in dims)
    except Exception:
        wsum = -1
    if wsum != 100:
        issues.append("%s C1 权重合计 = %s (应 100)" % (tag, wsum))
    # C2
    try:
        calc = sum(int(d.get("优势分", 0)) * int(d.get("权重", 0)) for d in dims) / 100.0
        given = float(s1.get("方向分"))
        if abs(calc - given) > 0.15:
            issues.append("%s C2 方向分对不上: 给出 %.2f, 按七维算 %.2f" % (tag, given, calc))
    except Exception as e:
        issues.append("%s C2 无法核算方向分 (%s)" % (tag, type(e).__name__))
    # C3
    try:
        given = float(s1.get("方向分"))
        side = s1.get("站边")
        if side == "主胜" and given < -0.3:
            issues.append("%s C3 说主胜但方向分 %.2f 利客" % (tag, given))
        if side == "客胜" and given > 0.3:
            issues.append("%s C3 说客胜但方向分 %+.2f 利主" % (tag, given))
    except Exception:
        pass
    # C4
    for label, key in (("盲判", "比分"),):
        sc = s1.get(key)
        sd = side_of(sc)
        if sd and sd != s1.get("站边"):
            issues.append("%s C4 %s比分 %s 属于 %s, 但站边写 %s" % (tag, label, sc, sd, s1.get("站边")))
    s2 = rec.get("stage2_vs_market") or {}
    sc2 = s2.get("最终比分")
    sd2 = side_of(sc2)
    if sd2 and sd2 != s2.get("最终站边"):
        issues.append("%s C4 最终比分 %s 属于 %s, 但最终站边写 %s" % (tag, sc2, sd2, s2.get("最终站边")))
    # 改判纪律
    if s2.get("是否改判") == "是" and str(s2.get("我漏掉的事实", "")).strip().lower() in ("", "none", "无"):
        issues.append("%s 改判了但没写「我漏掉的事实」" % tag)
    # C6 反编造
    ev = rec.get("evidence_s1") or ""
    if ev:
        for d in dims:
            evid = str(d.get("证据") or "")
            for dt in re.findall(r"\d{4}-\d{2}-\d{2}", evid):
                if dt not in ev:
                    issues.append("%s C6 日期 %s 不在证据包里 (%s维)" % (tag, dt, d.get("维度")))
        intel_missing = ("未获取" in ev and "情报文件里没有本场" in ev) or "情报文件不存在" in ev
        for d in dims:
            if d.get("维度") in ("阵容伤停", "天气场地", "裁判"):
                e = str(d.get("证据") or "")
                claims = re.search(r"伤缺|缺阵|停赛|受伤|缺席|首发|轮休", e)
                if claims and ("未获取" in e or "权重记0" in e.replace(" ", "")):
                    continue
                if claims and intel_missing:
                    issues.append("%s C6 情报缺失却断言伤停/首发 (%s维): %s" % (tag, d.get("维度"), e[:60]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    args = ap.parse_args()
    d = os.path.join(_ROOT, "data", "national")
    files = [os.path.join(d, "octa_%s.json" % args.date)] if args.date else \
        sorted(__import__("glob").glob(os.path.join(d, "octa_*.json")))
    if not files:
        print("没找到 octa_*.json"); return 1
    total_i = 0
    for f in files:
        recs = json.load(open(f, encoding="utf-8"))
        issues, warns = [], []
        for r in recs:
            check(r, issues, warns)
        confs = [(r.get("final") or {}).get("置信度分") for r in recs]
        if len(recs) >= 4 and len(set(confs)) == 1:
            warns.append("C5 全部 %d 场置信度分都是 %s —— 没有区分度" % (len(recs), confs[0]))
        elif len(recs) >= 4 and confs and all(isinstance(c, (int, float)) for c in confs):
            if max(confs) - min(confs) < 10:
                warns.append("C5 置信度分区间只有 %d 分 (%s~%s), 区分度偏弱" % (max(confs) - min(confs), min(confs), max(confs)))
        sides = Counter((r.get("final") or {}).get("站边") for r in recs)
        print("=== %s   %d 场 ===" % (os.path.basename(f), len(recs)))
        print("   站边分布: %s" % dict(sides))
        print("   置信度分: %s" % confs)
        if issues:
            print("   ✗ 问题 %d 条:" % len(issues))
            for i in issues:
                print("      - " + i)
        else:
            print("   ✓ 硬规则全部通过")
        for w in warns:
            print("   ⚠ " + w)
        print()
        total_i += len(issues)
    print("合计硬问题 %d 条" % total_i)
    return 1 if total_i else 0


if __name__ == "__main__":
    raise SystemExit(main())