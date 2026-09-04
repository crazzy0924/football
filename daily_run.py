# -*- coding: utf-8 -*-
"""
每日一键流程 (Phase 4 · 2026-08-15)

用法:
  python daily_run.py predict                     # 赛前: 体彩拉取 → 预测 → LLM分析 → 报告
  python daily_run.py predict --no-llm            # 同上, 跳过LLM分析(省token)
  python daily_run.py review 2026-08-15            # 赛后: 复盘 + 投注结算 + h2h回灌
  python daily_run.py review 2026-08-15 --results-text "A 2-1 B"   # 手输赛果复盘
  (review 不带日期参数默认复盘昨日 — 欧洲场凌晨完赛, 早上10点赛果已齐)

计划任务 (见 register_schedule.ps1):
  09:00  足球模型-每日预测  → daily_task_predict.cmd
  10:00  足球模型-每日复盘  → daily_task_review.cmd (复盘昨日)
  18:00  足球模型-午盘快照  → midday_snapshot.cmd
"""
from __future__ import annotations

import argparse
import io
import json
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


def _write_files_manifest() -> None:
    """生成 data/output/files.js (网页首页据此渲染有报告的日期, 避免404)"""
    import glob
    import re

    def _dates(pattern: str, prefix: str):
        # 只匹配标准日期文件名 (防止 review_analysis_*.html 之类混入)
        pat = re.compile("^" + re.escape(prefix) + r"\d{4}-\d{2}-\d{2}\.html$")
        out = []
        for p in sorted(glob.glob(os.path.join("data", "output", pattern))):
            base = os.path.basename(p)
            if pat.match(base):
                out.append(base[len(prefix):-len(".html")])
        return out

    pred_dates = _dates("predictions_*.html", "predictions_")
    rev_dates = _dates("review_*.html", "review_")
    ra_dates = _dates("review_analysis_*.html", "review_analysis_")
    early_dates = _dates("analysis_morning_*.html", "analysis_morning_")
    midday_dates = _dates("analysis_midday_*.html", "analysis_midday_")
    path = os.path.join("data", "output", "files.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.FOOT_FILES = {\n")
        f.write("  predictions: " + json.dumps(pred_dates) + ",\n")
        f.write("  reviews: " + json.dumps(rev_dates) + ",\n")
        f.write("  review_analysis: " + json.dumps(ra_dates) + ",\n")
        f.write("  early: " + json.dumps(early_dates) + ",\n")
        f.write("  midday: " + json.dumps(midday_dates) + ",\n")
        f.write("};\n")
    print("[清单] 已更新 " + path + " (" + str(len(pred_dates)) + "预测/" + str(len(rev_dates)) + "复盘/" + str(len(early_dates)) + "早盘/" + str(len(midday_dates)) + "午盘)")


RETRY_TASK_NAME = "足球模型-补推"


def _register_push_retry() -> None:
    """断网时注册每10分钟补推任务: 网络恢复后自动补推, 成功后自删"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        subprocess.run([
            "schtasks", "/Create", "/TN", RETRY_TASK_NAME,
            "/TR", f'cmd /c cd /d {root} && python daily_run.py push-retry',
            "/SC", "MINUTE", "/MO", "10", "/F",
        ], capture_output=True)
        print("[推送] 网络失败, 已注册每10分钟补推任务 (网通自动补回)")
    except Exception as e:
        print("[推送] 注册补推任务失败: " + str(e))


def _remove_push_retry() -> None:
    """补推成功后删除补推任务"""
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", RETRY_TASK_NAME, "/F"],
                       capture_output=True)
    except Exception:
        pass


def cmd_push_retry() -> None:
    """断网补推: 尝试推送; 成功或已同步则删除补推任务, 失败则10分钟后自动再试"""
    r = subprocess.run(["git", "push", "origin", "master"], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and ("up-to-date" in out or "->" in out):
        print("[补推] 推送成功/已同步, 删除补推任务")
        _remove_push_retry()
    else:
        print("[补推] 网络仍不通, 10分钟后自动重试")


def _git_sync() -> None:
    """CLAUDE.md 纪律: 汉化检查通过才提交推送; 断网自动注册补推自愈"""
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
    rc = _run(["git", "push", "origin", "master"])
    if rc != 0:
        # 断网自愈: 注册补推任务, 网通后自动补回并自删
        _register_push_retry()
        return
    print("[推送] 已推送 origin/master")
    _remove_push_retry()  # 若之前有补推任务残留, 一并清理


def cmd_predict(args) -> None:
    date_str = args.date or _today()

    # 1) 拉取今日比赛 (体彩为主, odds-api.io 兜底; --all-leagues 时纳入体彩开盘全部比赛)
    fetch_cmd = [sys.executable, "fetch_sporttery.py", date_str]
    if args.all_leagues:
        fetch_cmd.append("--all")
    rc = _run(fetch_cmd)
    if rc != 0:
        print("[警告] 体彩拉取失败, 尝试 odds-api.io 构建...")
        _run([sys.executable, "build_today_matches.py", date_str])

    # 2) 伤停自动侦察 (Bing公开搜索, 零注册零订阅)
    try:
        print("[伤停] 公开搜索侦察...")
        _run([sys.executable, "pipeline/injury_recon.py", date_str])
    except Exception as e:
        print("[警告] 伤停侦察跳过: " + str(e))

    # 3) 积分榜采集 (football-data.org, 免费档)
    try:
        from config import FOOTBALL_DATA_API_KEY
        if FOOTBALL_DATA_API_KEY:
            print("[积分榜] football-data.org 采集...")
            _run([sys.executable, "pipeline/standings_fetcher.py"])
    except Exception as e:
        print("[警告] 积分榜采集跳过: " + str(e))

    # 3) 伤停情报自动采集 (API-Football, 需 FOOTBALL_RAPIDAPI_KEY; 无key自动跳过)
    try:
        from config import FOOTBALL_RAPIDAPI_KEY
        if FOOTBALL_RAPIDAPI_KEY:
            print("[情报] API-Football 伤停采集...")
            _run([sys.executable, "pipeline/intel_fetcher.py", date_str])
    except Exception as e:
        print("[警告] 情报采集跳过: " + str(e))

    # 3b) 英超伤停 (官方 FPL API, 免费无key, 仅英超场次)
    try:
        _run([sys.executable, "pipeline/intel_fetcher_fpl.py", date_str])
    except Exception as e:
        print("[警告] FPL 伤停采集跳过: " + str(e))

    # 4) 预测 (可选 LLM 分析; 早盘/午盘只出七维分析存档页, 终盘出预测页)
    cmd = [sys.executable, "pipeline.py", "predict", "--matches-json", "data/today.json", "--stage", args.stage]
    if not args.no_llm:
        cmd.append("--llm")
    rc = _run(cmd)
    if rc != 0:
        print("[失败] 预测流程退出码 " + str(rc))
        sys.exit(rc)

    stage_cn = {"morning": "早盘", "midday": "午盘", "final": "终盘"}.get(args.stage, args.stage)
    if args.stage == "final":
        print("\n[完成] 终盘预测报告: data/output/predictions_" + date_str + ".html")
    else:
        print("\n[完成] " + stage_cn + "七维分析存档: data/output/analysis_" + args.stage + "_" + date_str + ".html")
    _write_files_manifest()
    _git_sync()

    # 死规矩: 终盘输出后必须对照工作自检表, 查偷懒现象
    if args.stage == "final":
        print("\n[自检] 终盘流程自检 (工作自检表)...\n")
        _run([sys.executable, "pipeline/self_check.py", date_str])


def cmd_review(args) -> None:
    # 默认复盘昨日 (欧洲场凌晨完赛, 早上10点赛果已齐)
    date_str = args.date or (datetime.now(BEIJING) - timedelta(days=1)).strftime("%Y-%m-%d")
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
    _write_files_manifest()
    _git_sync()


def main() -> None:
    parser = argparse.ArgumentParser(description="每日一键流程")
    sub = parser.add_subparsers(dest="command")

    p_predict = sub.add_parser("predict", help="赛前: 拉取赔率 + 预测 + LLM分析")
    p_predict.add_argument("--date", help="日期 YYYY-MM-DD (默认今天北京时间)")
    p_predict.add_argument("--no-llm", action="store_true", help="跳过LLM定性分析")
    p_predict.add_argument("--stage", choices=["morning", "midday", "final"], default="final",
                          help="早盘/午盘只出七维分析存档页, 终盘出预测页")
    p_predict.add_argument("--all-leagues", action="store_true",
                          help="纳入体彩开盘的全部比赛(含非五大联赛, 分析为主)")

    p_review = sub.add_parser("review", help="赛后: 复盘 + 投注结算 + h2h回灌")
    p_review.add_argument("date", nargs="?", default=None, help="日期 YYYY-MM-DD (默认昨日)")
    p_review.add_argument("--results-text", help="赛果文本 (例: 'A 2-1 B\\nC 0-0 D')")

    p_retry = sub.add_parser("push-retry", help="断网补推: 网通后自动推送并自删任务")

    args = parser.parse_args()
    if args.command == "predict":
        cmd_predict(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "push-retry":
        cmd_push_retry()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
