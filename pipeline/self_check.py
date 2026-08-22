# -*- coding: utf-8 -*-
"""
工作自检表 · 自动执行版 (2026-08-21 死规矩)

终盘输出之后自动对照《工作自检表.md》检查偷懒现象。
用法: python pipeline/self_check.py [日期YYYY-MM-DD]
输出: 打印报告 + 写 data/output/self_check_YYYY-MM-DD.json
硬性违规(偷懒): 汉化未过 / 未推送 / 复盘漏配 / 页面未显示一致性预警 / 补推任务残留
"""
from __future__ import annotations

import glob
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BEIJING = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _sh(cmd: list) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        blob = (r.stdout or b"") + (r.stderr or b"")
        for enc in ("utf-8", "cp936", "gbk"):
            try:
                return r.returncode, blob.decode(enc).strip()
            except Exception:
                continue
        return r.returncode, ""
    except Exception as e:
        return -1, str(e)


def main() -> None:
    date_str = sys.argv[1] if len(sys.argv) > 1 else _today()
    checks = []
    hard_fail = 0

    def add(cid, name, ok, detail, hard=False):
        nonlocal hard_fail
        if ok is False and hard:
            hard_fail += 1
        checks.append({"项": cid, "检查": name, "结果": "通过" if ok is True else ("违规" if ok is False else "提示"),
                       "详情": detail, "硬性": hard})

    # A1 时间自检 (信息性)
    now_s = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S 周%u")
    add("A1", "时间自检", True, f"自检时点 {now_s} (北京时间)")

    # B1 当天赔率快照数
    snaps = glob.glob(os.path.join("data", "state", "odds_snapshots", f"snapshot_{date_str}_*.json"))
    add("B1", "赔率快照留档", len(snaps) >= 2, f"{len(snaps)} 个快照", hard=False)

    # C2 一致性预警显示 (JSON flags 数 vs 早盘页出现次数)
    try:
        pred_path = os.path.join("data", "output", f"predictions_{date_str}.json")
        with open(pred_path, "r", encoding="utf-8") as f:
            preds = json.load(f)
        n_flags = sum(1 for p in preds if (p.get("flags") or {}))
        page_path = os.path.join("data", "output", f"analysis_morning_{date_str}.html")
        n_shown = 0
        if os.path.exists(page_path):
            with open(page_path, "r", encoding="utf-8") as f:
                n_shown = f.read().count("一致性预警")
        add("C2", "一致性预警已显示", n_shown >= n_flags,
            f"预测带预警 {n_flags} 场, 页面显示 {n_shown} 处", hard=True)
    except Exception as e:
        add("C2", "一致性预警已显示", None, f"检查失败: {e}", hard=False)

    # C1 联合约束: 有让球/大小球倾向的场次必须带 joint_top_scores
    try:
        missing = [p.get("home_team") for p in preds
                   if ((p.get("ah_handicap") or {}).get("edge") or {}).get("edge") is not None
                   and not p.get("joint_top_scores")]
        add("C1", "联合约束比分", not missing, f"缺失 {len(missing)} 场: {missing}", hard=True)
    except Exception:
        add("C1", "联合约束比分", None, "跳过", hard=False)

    # B5 情报矛盾检测块
    intel_path = os.path.join("data", "intel", f"{date_str}.txt")
    if os.path.exists(intel_path):
        with open(intel_path, "r", encoding="utf-8") as f:
            intel = f.read()
        add("B5", "情报矛盾检测", "情报矛盾检测" in intel,
            f"账本 {len(intel)} 字, 冲突 {intel.count('[冲突]')} 条")
    else:
        add("B5", "情报矛盾检测", None, "当日无情报账本")

    # D1 汉化检查
    rc, out = _sh([sys.executable, "pre_push_check.py"])
    add("D1", "汉化检查", rc == 0, out.splitlines()[-1] if out else "", hard=True)

    # E1 git 未推送检测
    rc, head = _sh(["git", "rev-parse", "HEAD"])
    rc2, origin = _sh(["git", "rev-parse", "origin/master"])
    if rc == 0 and rc2 == 0:
        ahead = head != origin
        add("E1", "推送同步", not ahead, "本地与远端一致" if not ahead else f"本地领先: {head[:8]} vs {origin[:8]}", hard=True)
    else:
        add("E1", "推送同步", None, "git 检查失败")

    # E1b 补推任务残留
    rc, out = _sh(["schtasks", "/Query", "/TN", "足球模型-补推"])
    add("E1b", "补推任务无残留", rc != 0, "无残留" if rc != 0 else "补推任务存在(上次推送未完成)", hard=True)

    # D6 终盘页左侧联赛导航 (2026-08-21用户永久要求)
    pred_html = os.path.join("data", "output", f"predictions_{date_str}.html")
    if os.path.exists(pred_html):
        with open(pred_html, "r", encoding="utf-8") as f:
            ph = f.read()
        add("D6", "终盘页联赛导航", "league-nav" in ph and "ln-btn" in ph,
            "左侧联赛菜单已渲染" if "league-nav" in ph else "终盘页缺少联赛导航", hard=True)
    else:
        add("D6", "终盘页联赛导航", None, "当日终盘页未生成")

    # D2 审计格式: 最近复盘分析页无对勾叉
    ra_files = sorted(glob.glob(os.path.join("data", "output", "review_analysis_*.html")))
    if ra_files:
        with open(ra_files[-1], "r", encoding="utf-8") as f:
            ra = f.read()
        bad = ra.count("✅") + ra.count("❌")
        add("D2", "复盘审计格式", bad == 0, f"最近复盘页 {os.path.basename(ra_files[-1])} 对勾叉 {bad} 个", hard=True)
    else:
        add("D2", "复盘审计格式", None, "暂无复盘分析页")

    # B3 复盘匹配率 (最近复盘分析页卡片数 vs 当日预测数)
    ra_files = sorted(glob.glob(os.path.join("data", "output", "review_analysis_*.html")))
    if ra_files:
        latest_date = os.path.basename(ra_files[-1])[len("review_analysis_"):-len(".html")]
        with open(ra_files[-1], "r", encoding="utf-8") as f:
            ra = f.read()
        n_cards = ra.count('<article class="match">')
        pred_path = os.path.join("data", "output", f"predictions_{latest_date}.json")
        n_preds = 0
        if os.path.exists(pred_path):
            with open(pred_path, "r", encoding="utf-8") as f:
                n_preds = len(json.load(f))
        ok = (n_cards == n_preds) if n_preds > 0 else None
        add("B3", "复盘匹配率", ok, f"{latest_date}: 复盘 {n_cards}/{n_preds} 场", hard=True)

    # E2 计划任务 Ready 数
    rc, out = _sh(["schtasks", "/Query", "/FO", "CSV"])
    # schtasks CSV 每行前缀带反斜杠 (如 "\足球模型-..."), 按包含匹配
    ready = sum(1 for ln in out.splitlines()
                if '足球模型-' in ln and ('"Ready"' in ln or '"就绪"' in ln))
    add("E2", "计划任务健康", ready == 6, f"{ready}/6 个 Ready", hard=False)

    # E3 新赛季CSV
    csvs = glob.glob(os.path.join("data", "historical_odds", "*_2026_2027.csv"))
    add("E3", "新赛季CSV", len(csvs) >= 1, f"{len(csvs)} 个 2026-27 CSV")

    # 汇总
    n_pass = sum(1 for c in checks if c["结果"] == "通过")
    n_fail = sum(1 for c in checks if c["结果"] == "违规")
    print("=" * 52)
    print(f"工作自检表 · {date_str} · {n_pass} 通过 / {n_fail} 违规 / {hard_fail} 硬性违规")
    print("=" * 52)
    for c in checks:
        mark = {"通过": "[OK]", "违规": "[违规]", "提示": "[--]"}.get(c["结果"], "[--]")
        hard = " (硬性)" if c["硬性"] else ""
        print(f"{mark} {c['项']} {c['检查']}{hard}: {c['详情'][:120]}")
    if hard_fail:
        print(f"\n🚨 发现 {hard_fail} 项硬性违规(偷懒), 必须立即处理!")
    else:
        print("\n✅ 无硬性违规, 终盘流程合格。")
    os.makedirs(os.path.join("data", "output"), exist_ok=True)
    with open(os.path.join("data", "output", f"self_check_{date_str}.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "n_pass": n_pass, "n_fail": n_fail,
                   "hard_fail": hard_fail, "checks": checks}, f, ensure_ascii=False, indent=2)
    print(f"[自检表] 报告已存 → data/output/self_check_{date_str}.json")


if __name__ == "__main__":
    main()
