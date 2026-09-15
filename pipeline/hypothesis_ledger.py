# -*- coding: utf-8 -*-
"""模型假设台账 —— 把"复盘归因"变成"可裁决的假设", 让迭代闭环真正闭合。

为什么需要它 (2026-09-15):
  复盘一直在产四维归因, 但从来没人消费 —— 每天的归因写完就躺在那, 没有变成
  任何一条模型假设。而我没有跨天记忆, 靠"更努力思考"不可能实现成长。
  所以把闭环外置成文件: 归因 → 假设(待验) → 配对检验裁决 → 采纳/否决。

分工:
  归因负责"发现问题", 配对检验负责"防止拍脑袋改"(t>2 才采纳)。
  少了后者, 自我迭代就是过拟合入口 —— xG 那次纯模型 t=-3.94, 进生产链路腰斩,
  就是活例子。

用法:
    python pipeline/hypothesis_ledger.py --scan     # 扫全部复盘页, 更新台账
    python pipeline/hypothesis_ledger.py            # 打印台账
输出: data/state/hypothesis_ledger.json
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LEDGER = os.path.join("data", "state", "hypothesis_ledger.json")

# 模式词典: 归因是 LLM 自由文本, 用关键词归拢成可比对的模式
BUCKETS = [
    ("盘口/赔率异动", ["赔率", "盘口", "资金", "异动", "升降", "水位", "降盘", "升盘", "受注"]),
    ("大小球偏差", ["大小球", "总进球", "大球", "小球", "进球数", "2.5", "3.5"]),
    ("强队高估/冷门", ["高估", "低估", "强队", "热门", "冷门", "爆冷"]),
    ("场外情报(伤停/轮换/战意)", ["伤停", "轮换", "战意", "缺席", "停赛", "首发", "阵容", "体能", "轮休"]),
    ("让球/亚盘", ["让球", "亚盘", "穿盘", "让一球", "让两球"]),
    ("波胆/比分", ["波胆", "比分"]),
    ("数据缺失/冷启动", ["缺失", "冷启动", "无盘口", "样本不足", "升班马", "新援", "首次交手"]),
    ("联赛特性", ["联赛风格", "节奏", "德甲", "意甲", "西甲", "英超", "法甲", "欧冠"]),
    ("随机性/意外", ["红牌", "点球", "乌龙", "失误", "意外", "运气", "偶然"]),
]

# 已有裁决结论的假设 (人工维护), 台账里标注状态, 避免重复立项
DECIDED = {
    "时间衰减": ("已采纳-仅PL", "配对检验 PL t=-2.36 显著 / FL1 t=+2.23 显著变差 / 总体无效"),
    "xG 融合": ("已否决", "生产链路 t=-2.72 但不显著于任何单赛季, 只填平市场差距 6.3%"),
    "押平": ("已否决", "平局概率无横截面区分度, 强行押平 52.7%→45.6%"),
    "下注信号": ("已否决", "样本外 1752 场与实盘 38 场均为反向指标"),
    # ── 2026-09-15 由台账模式立项并裁决 (复算: python tools/backtest_calibration.py) ──
    "波胆最低比分权重偏高": (
        "已否决",
        "实测 5402 场: 最高概率比分落在最低四档(0-0/1-0/0-1/1-1)占 84.5%, "
        "直接命中 12.1% (随机基准 9~11%)。低比分本就是最常见比分, 不是缺陷 —— "
        "归因里的抱怨是单场轶事"),
    "BTTS/大球偏高": (
        "已否决-方向相反",
        "实测显著**偏低**: 大2.5 -2.47pp(t=-3.68) / 大3.5 -1.72pp(t=-2.74) / "
        "BTTS -3.84pp(t=-5.67)。归因说偏高是单场观察到 57% 就下的结论, "
        "**单场轶事在聚合口径下会完全反向**"),
    "总进球被系统性低估": (
        "已裁决-不修",
        "偏差真实(大2.5 -2.47pp t=-3.68 / BTTS -3.84pp t=-5.67), 但修法无效: "
        "严格样本外(前两季定校准, 后两季检验)的 logit 平移校准, "
        "大2.5 Brier 0.2474→0.2475(t=0.23) / BTTS 0.2502→0.2504(t=0.17), 均无改善。"
        "**机理: 校准偏差(边际均值不匹配) != 预测质量差。** "
        "当前赛季进球率(3.05)高于历史(2.8), 边际偏差主要来自**赛制漂移**而非模型缺陷; "
        "全局平移只会把本来预测对的场次改坏, 两项错误刚好抵消。"
        "复算: python tools/test_goals_fix.py"),
}


def _load() -> dict:
    if os.path.exists(LEDGER):
        try:
            return json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            pass
    return {"patterns": {}, "decided": DECIDED, "scanned": []}


def extract_attributions(html: str) -> list[tuple]:
    """抓 D 四维归因, 返回 (命中/未中, 维度, 归因文本)。

    必须区分命中/未中: LLM 每条归因都会提到赔率/伤停这些固定维度, 全量统计的话
    每个模式都"天天出现", 毫无区分度 (第一版实测 6 个模式全是 25 天)。
    真正有信息的是 —— **未中**的场次里, 归因反复指向什么。
    """
    out = []
    pat = re.compile(
        r'verdict-(hit|miss)">[^<]*</span>\s*<b>([^<]*)</b></div>'
        r'<div class="meta">归因[:：]\s*([^<]{4,400})')
    for m in pat.finditer(html):
        v = "未中" if m.group(1) == "miss" else "命中"
        out.append((v, m.group(2).strip(), m.group(3).strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="扫描复盘页并更新台账")
    a = ap.parse_args()
    led = _load()

    files = sorted(glob.glob(os.path.join("data", "output", "review_analysis_*.html")))
    if a.scan:
        n_new = 0
        for f in files:
            date = os.path.basename(f)[len("review_analysis_"):-len(".html")]
            try:
                html = io.open(f, encoding="utf-8").read()
            except Exception:
                continue
            attrs = extract_attributions(html)
            if date not in led["scanned"]:
                led["scanned"].append(date)
            for verdict, dim, txt in attrs:
                for name, kws in BUCKETS:
                    if any(k in txt for k in kws):
                        key = ("未中:" if verdict == "未中" else "命中:") + name
                        e = led["patterns"].setdefault(
                            key, {"days": [], "count": 0, "samples": []})
                        e["count"] += 1
                        if date not in e["days"]:
                            e["days"].append(date)
                        if len(e["samples"]) < 3 and txt not in e["samples"]:
                            e["samples"].append(txt[:200])
                        n_new += 1
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("扫描 %d 份复盘页, 命中 %d 条归因 → %s" % (len(files), n_new, LEDGER))
        print()

    pats = led.get("patterns") or {}
    if not pats:
        print("台账为空, 先跑 --scan")
        return 0
    print("=" * 74)
    print("模型假设台账 · 按\"出现的天数\"排序 (天数比条数更可信)")
    print("=" * 74)
    print("%-26s %-6s %-8s %s" % ("模式", "天数", "条数", "首次~最近"))
    print("-" * 74)
    miss = {k: v for k, v in pats.items() if k.startswith("未中:")}
    for name, e in sorted(miss.items(), key=lambda kv: -len(kv[1]["days"])):
        ds = sorted(e["days"])
        print("%-30s %-6d %-8d %s ~ %s" % (name, len(ds), e["count"], ds[0], ds[-1]))
    print()
    print("已有裁决结论 (不再重复立项):")
    for k, v in (led.get("decided") or {}).items():
        print("  %-10s %-14s %s" % (k, v[0], v[1]))
    print()
    if not miss:
        print("(还没有未中样本)")
        return 0
    top = max(miss.items(), key=lambda kv: len(kv[1]["days"]))
    print("出现天数最多的模式是 [%s] (%d 天)。下面是它的原话样本:" % (
        top[0], len(top[1]["days"])))
    for s in top[1]["samples"][:3]:
        print("   - " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
