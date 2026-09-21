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

# Windows GBK修复: 强制UTF-8输出。
# 必须用 reconfigure, 不能新建 TextIOWrapper (2026-09-16 踩坑):
# 本模块会被 pipeline.py 导入, 而 pipeline.py 自己也包装一次 stdout ——
# 两层包装时第一层会失去引用被 GC, 其 __del__ 关掉底层 buffer,
# 之后所有 print 报 "I/O operation on closed file", 整个进程尾部崩掉。
# reconfigure 不产生新对象, 天然幂等。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

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
REVIEW_RETRY_TASK = "足球模型-补复盘"


def _register_review_retry(date_str: str) -> None:
    """复盘失败时注册每30分钟重试任务 (2026-09-18 加)。

    起因: 09-17 早上两个赛果源同时连不上(WinError 10061), 复盘直接退出码 1 ——
    **09-16 的复盘从此缺失, 一直没人发现**。推送那条路早就有断网自愈(补推任务),
    复盘这条一直没有: 同一个网络故障, 推送能自愈, 复盘丢一天。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        subprocess.run([
            "schtasks", "/Create", "/TN", REVIEW_RETRY_TASK,
            "/TR", f'cmd /c cd /d {root} && python daily_run.py review {date_str}',
            "/SC", "MINUTE", "/MO", "30", "/F",
        ], capture_output=True)
        print("[复盘] 拉取失败已注册每30分钟重试任务 (网通自动补回并自删)")
    except Exception as e:
        print("[复盘] 注册重试任务失败: " + str(e))


def _detach_delete_task(task_name: str, delay: int = 5) -> None:
    """脱离当前进程、延迟若干秒后删除计划任务 —— 2026-09-19 修。

    为什么不能直接删: 任务**正在运行时** schtasks /Delete 删自己会失败(被占用),
    而异常被吞掉、也没检查返回值 → **任务永远删不掉, 每10分钟空跑一次**。
    实测: 补推任务连续多次"结果 0(成功)", 但下次运行时间照旧, 一直挂着。
    做法: 起一个脱离的 PowerShell, 先睡几秒(等当前实例退出), 再删。
    """
    import base64
    ps = ("Start-Sleep -Seconds %d;"
          "Unregister-ScheduledTask -TaskName '%s' -Confirm:$false" % (delay, task_name))
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-EncodedCommand", enc],
                         creationflags=0x00000008,   # DETACHED_PROCESS
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _remove_review_retry() -> None:
    """复盘成功后删除重试任务 (必须脱离进程延迟删, 见 _detach_delete_task)"""
    _detach_delete_task(REVIEW_RETRY_TASK)


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
    """补推成功后删除补推任务 (必须脱离进程延迟删, 见 _detach_delete_task)"""
    _detach_delete_task(RETRY_TASK_NAME)


def _git_fetch_merge_push() -> int:
    """fetch + merge + push —— 不能裸推 (2026-09-21 修)。

    原因: **另一个会话也在往同一分支推** (它跑 my_preds 自动更新)。我们裸 git push
    只要远端动过就必然 non-fast-forward 被拒; 补推任务重试还是裸 push → 永远推不上去。
    实测后果: 09-20 08:16 起连续 9 个提交堆积在本地, 预测/复盘/分析全都没上 GitHub,
    而任务结果码一直是 0 (提交成功、推送失败), 从外面看不出问题。
    """
    _run(["git", "fetch", "origin"])
    rc = _run(["git", "merge", "origin/master", "-m", "合并远端最新提交"])
    if rc != 0:
        _run(["git", "merge", "--abort"])
        print("[推送] 与远端合并失败, 已回退合并 —— 请人工处理")
        return rc
    return _run(["git", "push", "origin", "master"])


def cmd_push_retry() -> None:
    """断网/被拒补推: 成功或已同步则删除补推任务, 失败则10分钟后自动再试"""
    rc = _git_fetch_merge_push()
    if rc == 0:
        print("[补推] 推送成功/已同步, 删除补推任务")
        _remove_push_retry()
    else:
        print("[补推] 仍未推成功, 10分钟后自动重试")


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
    rc = _git_fetch_merge_push()
    if rc != 0:
        # 自愈: 注册补推任务 (它同样走 fetch+merge+push), 成功后自删
        _register_push_retry()
        return
    print("[推送] 已推送 origin/master")
    _remove_push_retry()  # 若之前有补推任务残留, 一并清理


def cmd_predict(args) -> None:
    date_str = args.date or _today()

    # 终盘只有一个守卫: 当天已出过就退出 (防重复冻结哈希链)。
    #
    # **时点不在这里判** (2026-09-17 用户拍板, 拆掉此前三层补丁)。
    # 三层补丁的来由, 都是因为"用固定/半固定钟点去猜跨时区赛程":
    #   1) 固定 21:00 → 首场 20:00 就开踢了
    #   2) 每30分钟唤起 + 最早开赛前90分钟闸门 → 触发器用了 -Once, 第二天不跑
    #   3) 改成每天触发 → 00:00 那一跳用前一天的赛程判时点, 给新一天提前 22 小时出终盘
    # 现在改为: tools/schedule_final.py 拉当日赛程, 用 business_date + kickoff_time
    # 拼出**绝对开赛时间**, 算出"最早开赛前 90 分钟", 直接把计划任务设到那个时刻。
    # 计划任务每天只跑一次, 时间由赛程决定 —— 这里不需要再判一次。
    if args.stage == "final" and not getattr(args, "force", False):
        _flag = os.path.join("data", "state", "final_done_" + date_str)
        if os.path.exists(_flag):
            print("[临盘] " + date_str + " 终盘已出过, 跳过")
            return

    # 1) 拉取今日比赛 (体彩为主, odds-api.io 兜底; --all-leagues 时纳入体彩开盘全部比赛)
    fetch_cmd = [sys.executable, "fetch_sporttery.py", date_str]
    if args.all_leagues:
        fetch_cmd.append("--all")
    rc = _run(fetch_cmd)
    if rc != 0:
        # 2026-09-15 教训: 体彩失败曾静默走兜底 —— 而兜底脚本 build_today_matches.py
        # 不填 kickoff_time, 且会返回刚踢完的场次。结果: 早盘把 4 场已经结束的比赛
        # (0-2/2-1/5-3/4-1) 又"预测"了一遍, 没有任何人发现, 直到翻日志才查出来。
        # 这里先重试一次; 仍失败就大声报警 —— 兜底可以走, 但失败必须可见。
        print("[盘口] 体彩拉取失败, 重试一次...")
        rc = _run(fetch_cmd)
    if rc != 0:
        print("")
        print("=" * 62)
        print("[严重] 体彩抓取失败, 本轮将走 odds-api.io 兜底!")
        print("       兜底数据不含 kickoff_time, 且可能带上已结束场次,")
        print("       按时间做的过滤会失效 → 请务必核对 data/today.json 是否可信。")
        print("       手工重跑: python fetch_sporttery.py " + date_str)
        print("=" * 62)
        print("")
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

    # 3c) SofaScore 盘口 (早盘 + 午盘 + 终盘; 真实动态大小球阶梯 + 1X2 + 亚盘 + 双进球)
    # 2026-09-11: 午盘(18:00)也抓 —— 临场盘口更准, 终盘失败还有午盘兜底。
    # 2026-09-12: 早盘(09:00)也抓 —— 实测当天早盘 21 场只有 12 场有盘口(57%),
    #             因为早盘用的是上一班的旧快照; 且早/午/终三个时点才看得出盘口移动。
    if args.stage in ("morning", "midday", "final"):
        # 2026-09-13 教训: 抓取失败曾被 try/except 静默吞掉, 预测拿着昨天的旧盘口照跑不误
        # (当天早盘/午盘两次抓取全挂, 13 场预测用的是 09-12 21:13 的旧快照)。
        # 这里比对文件 mtime: 本轮没写成功就大声报警, 不再静默降级。
        _odds_fp = os.path.join("data", "state", "sofascore_odds.json")
        _odds_before = os.path.getmtime(_odds_fp) if os.path.exists(_odds_fp) else 0.0
        try:
            print("[盘口] SofaScore 抓取...")
            _run([sys.executable, "pipeline/odds_fetcher_sofascore.py",
                  date_str, "--stage", args.stage])
        except Exception as e:
            print("[警告] SofaScore 盘口跳过: " + str(e))
        _odds_after = os.path.getmtime(_odds_fp) if os.path.exists(_odds_fp) else 0.0
        if _odds_after <= _odds_before:
            print("")
            print("=" * 62)
            print("[严重] SofaScore 盘口本轮未更新, 预测将使用旧快照!")
            print("       文件: " + _odds_fp)
            print("       旧快照时间: %s (距今 %.1f 小时)" % (
                datetime.fromtimestamp(_odds_after).strftime("%Y-%m-%d %H:%M:%S"),
                (datetime.now().timestamp() - _odds_after) / 3600.0))
            print("       大小球/亚盘线可能不是当天盘口, 结论不可信 → 请手工重跑:")
            print("       请手工执行: python pipeline/odds_fetcher_sofascore.py %s --stage %s" % (date_str, args.stage))
            print("=" * 62)
            print("")

    # 4) 预测 (可选 LLM 分析; 早盘/午盘只出七维分析存档页, 终盘出预测页)
    # **必须显式传 --date** (2026-09-19 修): 终盘常在午夜后跑, 不传的话 pipeline.py
    # 用"当前日期"命名产物 —— 实测 09-19 00:00 那次按 09-18 抓的数据, 却写成了
    # predictions_2026-09-19.json。上面 fetch_sporttery / odds_fetcher 都传了日期,
    # 只有这里漏了, 于是"内容对、文件名错"。
    cmd = [sys.executable, "pipeline.py", "predict", "--matches-json", "data/today.json",
           "--stage", args.stage, "--date", date_str]
    if not args.no_llm:
        cmd.append("--llm")
    rc = _run(cmd)
    if rc != 0:
        print("[失败] 预测流程退出码 " + str(rc))
        sys.exit(rc)

    # 终盘成功才落"今天已出"标记 (避免一天出多次 / 重复冻结哈希链)
    if args.stage == "final":
        try:
            open(os.path.join("data", "state", "final_done_" + date_str), "w").close()
        except Exception:
            pass

    # 早盘/午盘跑完后重排终盘时刻 (2026-09-17 用户拍板: 用"算"取代"猜")。
    # 排程器拉当日赛程 → 用 business_date + kickoff_time 拼出绝对开赛时间 →
    # 把终盘任务设到"最早开赛前 90 分钟"。每天重排一次, 时间随赛程走。
    if args.stage in ("morning", "midday"):
        try:
            print("[排程] 重排终盘时刻...")
            _run([sys.executable, "tools/schedule_final.py"])
        except Exception as e:
            print("[排程] 跳过: " + str(e)[:60])

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
        # 断网自愈 (2026-09-18): 不要直接丢一天 —— 注册重试任务, 网通后自动补回。
        # 注意: 重试任务跑的是同一个命令, 成功时会走到下面 _remove_review_retry() 自删。
        _register_review_retry(date_str)
        sys.exit(rc)
    _remove_review_retry()  # 成功则清掉可能残留的重试任务

    # 赛果回灌全库 (h2h 纪律)
    results_path = os.path.join("data", "output", f"results_{date_str}.json")
    if os.path.exists(results_path):
        _run([sys.executable, "h2h.py", "--append", results_path])
    else:
        print("[跳过] 未找到 " + results_path + ", 跳过h2h回灌")
    # 假设台账自动更新 (2026-09-15): 复盘归因必须被"消费", 否则闭环断在这里。
    # 这里每天扫一次, 把"未中"场次的归因归拢成模式; 周复盘直接读台账。
    try:
        _run([sys.executable, "pipeline/hypothesis_ledger.py", "--scan"])
    except Exception as e:
        print("[警告] 假设台账更新跳过: " + str(e))

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
    # 手动强制出终盘 (用户临时叫): 绕过"最早开赛前90分钟"与"今天已出过"两道闸门。
    # 注意: 强制重跑不应重复写哈希链台账 —— 调用方需自行设 FOOTBALL_NO_FREEZE=1。
    p_predict.add_argument("--force", action="store_true",
                          help="手动强制出终盘, 绕过临盘时点与当日去重闸门")
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
