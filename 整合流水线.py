# -*- coding: utf-8 -*-
"""
整合流水线 · 项目总监一键入口 (v1.0)

把 sky4.0 量化组 与 克劳德交叉分析师 整合为一条自动化链路:
  sky4.0 出数 → 克劳德独立交叉 → 同路/分歧合并 → 我的预测 latest.md → 渲染 → 推送

用法:
  python 整合流水线.py full --date 2026-09-08            # 全流程(含克劳德 DeepSeek 交叉)
  python 整合流水线.py full --date 2026-09-08 --no-cross  # 跳过克劳德, 用结构化信号兜底合并
  python 整合流水线.py merge --date 2026-09-08            # 只合并已有 claude_cross_*.json
  python 整合流水线.py render --date 2026-09-08           # 只渲染 + 推送
  python 整合流水线.py full --date 2026-09-08 --include-elc  # 纳入英冠

计划任务 (22:10 无人值守):
  schtasks /Create /F /TN "足球模型-整合流水线" /SC DAILY /ST 22:10 /TR "...\整合流水线.cmd"
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SKY_LIVE = Path(r"D:\足球大模型1.0")              # 活量化系统 (计划任务指向, 有 DEEPSEEK key)
SKY = Path(r"E:\足球大模型\sky日记")              # 克劳德侧副本 (claude_cross.py 所在)
MY = Path(r"E:\足球大模型\我的预测")              # 唯一「我的预测」产出
BEIJING = timezone(timedelta(hours=8))


def active_sky() -> Path:
    """桥接: 读活量化系统 (D盘); 若不存在则回退 E盘 副本"""
    return SKY_LIVE if SKY_LIVE.exists() else SKY

DIR_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
LEAGUE_NAMES = {
    "PL": "英超", "PD": "西甲", "BL1": "德甲", "SA": "意甲", "FL1": "法甲",
    "UCL": "欧冠", "ELC": "英冠",
}


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _run(cmd: list[str], cwd: Path | None = None) -> int:
    print(">>> " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None)
    return r.returncode


# ---------- 第一步: sky4.0 产出确认 ----------
def sky_ready(date: str) -> bool:
    src = active_sky()
    pred = src / "data" / "output" / f"predictions_{date}.json"
    note = src / "data" / "output" / f"analysis_notes_final_{date}.json"
    return pred.exists() and note.exists()


def ensure_sky(date: str) -> bool:
    """sky4.0 终盘产出若缺失, 尝试在活系统补跑 (21:00 计划任务已跑则跳过)"""
    if sky_ready(date):
        print(f"[sky4.0] {date} 终盘产出已存在 ({active_sky()}), 跳过补跑")
        return True
    print(f"[sky4.0] {date} 终盘产出缺失, 尝试补跑 daily_run predict --stage final --llm...")
    rc = _run([sys.executable, "daily_run.py", "predict", "--date", date, "--stage", "final", "--llm"], cwd=active_sky())
    return rc == 0 and sky_ready(date)


# ---------- 第二步: 克劳德交叉 ----------
def cross_out(date: str) -> Path:
    """克劳德交叉结果输出到 E盘 副本 (不写活系统)"""
    return SKY / "data" / "output" / f"claude_cross_{date}.json"


def run_cross(date: str, include_elc: bool) -> bool:
    cmd = [sys.executable, "pipeline/claude_cross.py", date,
           "--sky-dir", str(active_sky()), "--out", str(cross_out(date))]
    if include_elc:
        cmd.append("--include-elc")
    rc = _run(cmd, cwd=SKY)
    return rc == 0 and cross_out(date).exists()


def structural_fallback(date: str, include_elc: bool) -> list[dict]:
    """克劳德 LLM 不可用时的结构化兜底: 用模型vs市场方向给保守判定"""
    sys.path.insert(0, str(SKY))
    from pipeline import claude_cross as cc  # noqa: E402
    cc.set_sky_dir(str(active_sky()))
    if include_elc:
        cc.FOCUS_CODES.add("ELC")
    preds = json.loads((active_sky() / "data" / "output" / f"predictions_{date}.json").read_text(encoding="utf-8"))
    preds = cc.dedupe_predictions(preds)
    out = []
    for p in preds:
        if p.get("league_code") not in cc.FOCUS_CODES:
            continue
        odds = p.get("odds") or {}
        mkt = cc.market_direction(odds)      # 克劳德方向锚 = 市场 (方向信市场)
        sky = cc.pick_direction(p)           # sky4.0 显示的看好方向
        cold = p.get("cold_start", False)
        flags = cc.structural_flags(p)

        fav = odds.get(mkt, 0) if mkt in ("home", "away") else 0
        reverse_strong = (mkt in ("home", "away") and sky in ("home", "away")
                          and sky != mkt and fav and fav <= 1.8)
        diverge = (sky in ("home", "away", "draw") and mkt in ("home", "away", "draw")
                   and sky != mkt)

        # 死规矩⑤: 冷启动永不投注, 但方向照给 (用户确认: 保持给方向, 标「低·冷启动」)
        if cold:
            verdict, level = "保留", "无"
            direction = DIR_CN.get(mkt, "跳过") if mkt in DIR_CN else "跳过"
            conf = "低·冷启动"
        elif reverse_strong:
            verdict, level, direction, conf = "反对", "P0", DIR_CN.get(mkt, "跳过"), "低"
        elif diverge:
            verdict, level, direction, conf = "反对", "无", DIR_CN.get(mkt, "跳过"), "低"
        else:
            verdict, level, direction, conf = "同意", "无", DIR_CN.get(mkt, "跳过"), "低"

        out.append({
            "home": p.get("home_team", "?"), "away": p.get("away_team", "?"),
            "league": p.get("league_code", ""),
            "判定": verdict, "方向": direction,
            "置信度": conf, "问题等级": level,
            "首选比分": "", "大小球": "跳过",
            "理由": "[结构化兜底: 克劳德LLM不可用, 方向取市场锚]",
            "交叉要点": f"sky看好{sky} vs 市场{mkt}" + (("; " + "; ".join(flags)) if flags else ""),
            "structural_flags": flags,
        })
    return out


# ---------- 第三步: 同路/分歧合并 ----------
def _relation_label(v: dict) -> str:
    """判定 + 问题等级 → 「与sky4.0」列标签"""
    verdict = v.get("判定", "")
    level = v.get("问题等级", "")
    if level == "P0":
        return "分歧·P0"
    if verdict == "反对":
        return "分歧"
    if level == "P2":
        return "同路·OU分歧"
    if verdict == "保留":
        return "同路·保守"
    return "同路"


def load_team_cn() -> dict:
    """从活系统加载 英文→中文 队名映射 (全中文纪律)"""
    sys.path.insert(0, str(active_sky()))
    try:
        from pipeline.reporter import TEAM_CN
        return TEAM_CN
    except Exception:
        return {}


def merge(date: str, verdicts: list[dict]) -> str:
    """把克劳德交叉结果 + sky 终盘, 合并为 我的预测/latest.md 内容 (队名汉化)"""
    cn_map = load_team_cn()

    def cn(name):
        return cn_map.get(name, name)

    preds = json.loads((active_sky() / "data" / "output" / f"predictions_{date}.json").read_text(encoding="utf-8"))
    kick = {f"{p.get('home_team', '?')} vs {p.get('away_team', '?')}": p.get("kickoff_time", "") for p in preds}

    def _fmt_ko(v: dict) -> str:
        k = f"{v.get('home')} vs {v.get('away')}"
        t = kick.get(k, "")
        return t[:5] if t else ""

    lines: list[str] = []
    lines.append(f"我的全维度预测 · {date}（{len(verdicts)} 场 · 交叉 sky4.0）")
    lines.append("## 终版（方向/比分/大小球）")
    lines.append("| 场次 | 我的方向 | 首选比分 | 大小球 | 与sky4.0 |")
    lines.append("|---|---|---|---|---|")

    p0_list, p1_list, p2_list, diverge_list, agree_list = [], [], [], [], []
    for v in verdicts:
        ko = _fmt_ko(v)
        match_name = f"{cn(v.get('home', '?'))} 对 {cn(v.get('away', '?'))}" + (f" {ko}" if ko else "")
        direction = f"{v.get('方向', '跳过')}（{v.get('置信度', '低')}）"
        score = v.get("首选比分") or "—"
        ou = v.get("大小球") or "跳过"
        rel = _relation_label(v)
        lines.append(f"| {match_name} | {direction} | {score} | {ou} | {rel} |")

        level = v.get("问题等级", "")
        cn_pair = f"{cn(v.get('home', '?'))} 对 {cn(v.get('away', '?'))}"
        if level == "P0":
            p0_list.append(f"{cn_pair}：{v.get('交叉要点') or v.get('理由', '')}")
        elif level == "P1":
            p1_list.append(f"{cn_pair}：{v.get('交叉要点') or v.get('理由', '')}")
        elif level == "P2":
            p2_list.append(f"{cn_pair}：{v.get('交叉要点') or v.get('理由', '')}")
        elif v.get("判定") == "反对":
            diverge_list.append(f"{cn_pair}：{v.get('交叉要点') or v.get('理由', '')}")
        if v.get("判定") in ("同意", "保留"):
            agree_list.append(v.get("方向", ""))

    lines.append("## 与 sky4.0 交叉要点")
    if p0_list:
        lines += [f"* P0 反向错误：{x}" for x in p0_list]
    if p1_list:
        lines += [f"* P1 错标冷启动：{x}" for x in p1_list]
    if p2_list:
        lines += [f"* P2 大小球分歧：{x}" for x in p2_list]
    if diverge_list:
        lines += [f"* 方向分歧（不跟）：{x}" for x in diverge_list]
    if agree_list:
        lines.append(f"* 共识场（同路）：{len(agree_list)} 场方向一致，命中率权重更高。")
    lines.append("> 本页为 sky4.0 量化 + 克劳德独立交叉后的唯一预测，仅作 AI 学习与研究，不构成投注建议。")

    return "\n".join(lines)


# ---------- 第四步: 渲染 + 推送 ----------
def push_my_preds(date: str) -> bool:
    """把「我的预测」HTML 从 D 盘(SSH canonical)推送到 GitHub Pages.

    死规矩②: 推送前必须跑 pre_push_check 汉化检查, 不通过不 push。
    """
    import shutil
    src = MY / "html"
    dst = SKY_LIVE / "my_preds"
    if not dst.exists():
        print(f"[推送] 目标目录不存在: {dst}")
        return False
    for f in src.glob("*.html"):
        shutil.copyfile(f, dst / f.name)
    _run(["git", "add", "my_preds"], cwd=SKY_LIVE)
    rc = _run(["python", "pre_push_check.py"], cwd=SKY_LIVE)
    if rc != 0:
        print("[推送] 汉化检查未通过, 跳过推送 (已留本地)")
        return False
    rc = _run(["git", "commit", "-m", f"我的预测: {date} (克劳德交叉 sky4.0) 推送"], cwd=SKY_LIVE)
    if rc not in (0, 1):
        print("[推送] 提交失败")
        return False
    rc = _run(["git", "push", "origin", "master"], cwd=SKY_LIVE)
    if rc == 0:
        print("[推送] 已推送 https://crazzy0924.github.io/football/my_preds/latest.html")
        return True
    print("[推送] 推送失败(网络/凭据), 文件已留本地")
    return False


def render_and_push(date: str) -> bool:
    for ps in ("render_predictions.ps1", "build_index.ps1"):
        rc = _run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(MY / ps)])
        if rc != 0:
            print(f"[渲染] {ps} 退出码 {rc} (继续)")
    push_my_preds(date)
    latest = MY / "html" / f"predictions_{date}.html"
    return latest.exists()


# ---------- 主命令 ----------
def cmd_full(args) -> None:
    date = args.date or _today()
    if not ensure_sky(date):
        print(f"[整合] sky4.0 {date} 终盘产出仍缺失, 终止 (请先跑 21:00 终盘)")
        sys.exit(1)

    if args.no_cross:
        verdicts = structural_fallback(date, args.include_elc)
        cross_out(date).write_text(json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[克劳德] 已用结构化兜底生成 {len(verdicts)} 场交叉结果")
    else:
        if not run_cross(date, args.include_elc):
            print("[克劳德] 交叉失败, 回退结构化兜底...")
            verdicts = structural_fallback(date, args.include_elc)
        else:
            verdicts = json.loads(cross_out(date).read_text(encoding="utf-8"))

    if not verdicts:
        print("[整合] 今日无五大联赛/欧冠场次, 不产出「我的预测」")
        return

    md = merge(date, verdicts)
    (MY / "latest.md").write_text(md, encoding="utf-8")
    print(f"[合并] 已写 我的预测/latest.md ({len(verdicts)} 场)")

    if not args.no_push:
        ok = render_and_push(date)
        print("[整合] 渲染+推送 " + ("完成" if ok else "部分失败(见上)"))
    print("\n[整合] 全流程完成 ✅")


def cmd_merge(args) -> None:
    date = args.date or _today()
    path = cross_out(date)
    if not path.exists():
        print(f"[合并] 未找到 {path}, 先跑 full 或 claude_cross")
        sys.exit(1)
    verdicts = json.loads(path.read_text(encoding="utf-8"))
    md = merge(date, verdicts)
    (MY / "latest.md").write_text(md, encoding="utf-8")
    print(f"[合并] 已写 我的预测/latest.md ({len(verdicts)} 场)")


def cmd_render(args) -> None:
    render_and_push(args.date or _today())


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="整合流水线 (sky4.0 + 克劳德 → 我的预测)")
    sub = ap.add_subparsers(dest="command")

    p_full = sub.add_parser("full", help="全流程")
    p_full.add_argument("--date")
    p_full.add_argument("--no-cross", action="store_true", help="跳过克劳德LLM, 用结构化兜底")
    p_full.add_argument("--no-push", action="store_true", help="只生成本地文件, 不渲染不推送")
    p_full.add_argument("--include-elc", action="store_true", help="纳入英冠")

    p_merge = sub.add_parser("merge", help="只合并已有 claude_cross")
    p_merge.add_argument("--date")

    p_render = sub.add_parser("render", help="只渲染+推送")
    p_render.add_argument("--date")

    args = ap.parse_args()
    if args.command == "full":
        cmd_full(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "render":
        cmd_render(args)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
