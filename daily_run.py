# -*- coding: utf-8 -*-
"""
每日一键流程 (Phase 4 · 2026-08-15)

用法:
  python daily_run.py predict                     # 赛前: 体彩拉取 → 预测 → LLM分析 → 报告
  python daily_run.py predict --no-llm            # 同上, 跳过LLM分析(省token)
  python daily_run.py review 2026-08-15            # 赛后: 复盘 + 投注结算 + h2h回灌
  python daily_run.py review 2026-08-15 --results-text "A 2-1 B"   # 手输赛果复盘

计划任务 (见 register_schedule.ps1):
  09:00  足球模型-每日预测  → daily_task_predict.cmd
  21:30  足球模型-每日复盘  → daily_task_review.cmd
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# Windows GBK修复: 强制UTF-8输出
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BEIJING = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _run(cmd: list[str]) -> int:
    print(">>> " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def _git_sync() -> None:
    """CLAUDE.md 纪律: 汉化检查通过才提交推送"""
    rc = _run([sys.executable, "pre_push_check.py"])
    if rc != 0:
        print("[推送] 汉化检查未通过, 跳过自动提交推送 (请人工处理)")
        return
    _run(["git", "add", "-A"])
    today = _today()
    rc = _run(["git", "commit", "-m", f"每日自动: {today} 预测+复盘产物 (汉化检查通过)"])
    if rc not in (0, 1):  # 1 = 无变更可提交
        print("[推送] 提交失败, 跳过推送")
        return
    _run(["git", "push", "origin", "master"])
    print("[推送] 已尝试推送 origin/master")


def cmd_predict(args) -> None:
    date_str = args.date or _today()

    # 0) 追补昨日复盘 (凌晨完赛的欧洲场: 增量幂等, 无赛果优雅退出)
    yest = (datetime.now(BEIJING) - timedelta(days=1)).strftime("%Y-%m-%d")
    yest_pred = os.path.join("data", "output", f"predictions_{yest}.json")
    if os.path.exists(yest_pred):
        print("[追补] 复盘昨日 " + yest + " (凌晨完赛的欧洲场)...")
        rc_y = _run([sys.executable, "daily_run.py", "review", yest])
        if rc_y != 0:
            print("[追补] 昨日复盘未完成 (缺赛果或已处理完), 继续今日预测")

    # 1) 拉取今日比赛 (体彩为主, odds-api.io 兜底)
    rc = _run([sys.executable, "fetch_sporttery.py", date_str])
    if rc != 0:
        print("[警告] 体彩拉取失败, 尝试 odds-api.io 构建...")
        _run([sys.executable, "build_today_matches.py", date_str])

    # 2) 伤停情报自动采集 (API-Football, 需 FOOTBALL_RAPIDAPI_KEY; 无key自动跳过)
    try:
        from config import FOOTBALL_RAPIDAPI_KEY
        if FOOTBALL_RAPIDAPI_KEY:
            print("[情报] API-Football 伤停采集...")
            _run([sys.executable, "pipeline/intel_fetcher.py", date_str])
    except Exception as e:
        print("[警告] 情报采集跳过: " + str(e))

    # 3) 预测 (可选 LLM 分析)
    cmd = [sys.executable, "pipeline.py", "predict", "--matches-json", "data/today.json"]
    if not args.no_llm:
        cmd.append("--llm")
    rc = _run(cmd)
    if rc != 0:
        print("[失败] 预测流程退出码 " + str(rc))
        sys.exit(rc)

    print("\n[完成] 预测报告: data/output/predictions_" + date_str + ".html")
    _git_sync()


def cmd_review(args) -> None:
    date_str = args.date or _today()
    cmd = [sys.executable, "pipeline.py", "review", date_str]
    if args.results_text:
        cmd += ["--results-text", args.results_text]
    rc = _run(cmd)
    if rc != 0:
        print("[失败] 复盘流程退出码 " + str(rc))
        sys.exit(rc)

    # 赛果回灌全库 (h2h 纪律)
    results_path = os.path.join("data", "output", f"results_{date_str}.json")
    if os.path.exists(results_path):
        _run([sys.executable, "h2h.py", "--append", results_path])
    else:
        print("[跳过] 未找到 " + results_path + ", 跳过h2h回灌")
    _git_sync()


def main() -> None:
    parser = argparse.ArgumentParser(description="每日一键流程")
    sub = parser.add_subparsers(dest="command")

    p_predict = sub.add_parser("predict", help="赛前: 拉取赔率 + 预测 + LLM分析")
    p_predict.add_argument("--date", help="日期 YYYY-MM-DD (默认今天北京时间)")
    p_predict.add_argument("--no-llm", action="store_true", help="跳过LLM定性分析")

    p_review = sub.add_parser("review", help="赛后: 复盘 + 投注结算 + h2h回灌")
    p_review.add_argument("date", nargs="?", default=None, help="日期 YYYY-MM-DD (默认今天北京时间)")
    p_review.add_argument("--results-text", help="赛果文本 (例: 'A 2-1 B\\nC 0-0 D')")

    args = parser.parse_args()
    if args.command == "predict":
        cmd_predict(args)
    elif args.command == "review":
        cmd_review(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
