# -*- coding: utf-8 -*-
"""按当日赛程排定终盘时刻 —— 用"算"取代"猜"。

用户拍板 (2026-09-17): 不再用固定钟点 + 闸门补丁, 直接:
  1. 读当日体彩快照
  2. 用 business_date + kickoff_time 拼出**绝对开赛时间** (消除跨天歧义)
  3. 取"还没开赛的场次里最早的那个", 目标时刻 = 它 - 90 分钟
  4. 把【足球模型-终盘预测】设为**每天一次**在该时刻触发
  5. 目标时刻已过 → 不安排, 打印提示

为什么拆掉旧做法: 固定钟点(21:00/20:00)与跨时区赛程天生错位; 改成"每30分钟唤起 +
闸门判断"后又要靠"最早开赛前90分钟 / 每天触发 / 跨天防线"三层补丁兜, 每加一层
多一个出错点。直接算出唯一时刻, 只有一条路径。

用法:
    python tools/schedule_final.py             # 排今天
    python tools/schedule_final.py --dry-run   # 只算不改任务
"""
import argparse
import base64
import glob
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TASK = "足球模型-终盘预测"
LEAD_MIN = 90


def _ps(cmd: str) -> str:
    """用 -EncodedCommand 执行 PowerShell —— 绕开中文任务名在命令行上的编码问题。"""
    enc = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip()


def load_slate(date_str: str) -> list:
    """读当日最新快照 (场次最多的那份)。"""
    fs = sorted(glob.glob(os.path.join("data", "state", "odds_snapshots",
                                       "snapshot_%s_*.json" % date_str)))
    best, best_n = None, -1
    for f in fs:
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if len(d) > best_n:
            best, best_n = d, len(d)
    return best or []


def kickoff_dt(m: dict, fallback_date: str):
    """business_date + kickoff_time → 绝对开赛时间。缺 business_date 时退回 fallback。

    **体彩的 businessDate 是"比赛日", 不是开赛那一天** (2026-09-17 实测确认):
    比赛日 D 覆盖 D 白天 → D+1 早上, 所以凌晨(12:00 前)的场次属于**前一天**的比赛日。
    实测: 比赛日 09-17 的两场 ko=01:00/03:30, 实际开赛是 09-18 凌晨。
    这条规则 pipeline.py 里一直有(if hh < 12: +1 天), 我前面几轮自己怀疑掉了, 绕了远路。
    """
    kt = (m.get("kickoff_time") or "").strip()
    if not kt or len(kt) < 5:
        return None
    bd = (m.get("business_date") or fallback_date).strip()
    try:
        dt = datetime.strptime(bd + " " + kt[:5], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if dt.hour < 12:
        dt += timedelta(days=1)
    return dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now()

    slate = load_slate(a.date)
    if not slate:
        print("[排程] %s 没有快照, 无法排 —— 保持原计划任务不动" % a.date)
        return 1

    rows = []
    for m in slate:
        dt = kickoff_dt(m, a.date)
        if dt:
            rows.append((dt, m))
    rows.sort(key=lambda x: x[0])
    upcoming = [(dt, m) for dt, m in rows if dt > now]

    print("[排程] %s 共 %d 场, 其中有开赛时间的 %d 场, 未开赛 %d 场" % (
        a.date, len(slate), len(rows), len(upcoming)))
    for dt, m in rows[:6]:
        mark = "未开赛" if dt > now else "已开赛"
        print("   %s  %-6s %s vs %s  [%s]" % (
            dt.strftime("%m-%d %H:%M"), m.get("league_code"),
            m.get("home_team", ""), m.get("away_team", ""), mark))
    if not upcoming:
        print()
        print("[排程] 今天没有未开赛的场次 → 不安排终盘")
        print("       需要临时出终盘: python daily_run.py predict --stage final --force")
        return 2

    earliest = upcoming[0][0]
    target = earliest - timedelta(minutes=LEAD_MIN)
    print()
    print("[排程] 最早开赛 %s → 终盘目标 %s (提前 %d 分钟)" % (
        earliest.strftime("%m-%d %H:%M"), target.strftime("%m-%d %H:%M"), LEAD_MIN))

    if target <= now:
        print("[排程] 目标时刻已过 (现在 %s) → 不安排" % now.strftime("%H:%M"))
        print("       需要立即出终盘: python daily_run.py predict --stage final --force")
        return 2

    at = target.strftime("%Y-%m-%dT%H:%M:00")
    if a.dry_run:
        print("[排程] --dry-run: 本应把任务设为每天 %s 触发" % target.strftime("%H:%M"))
        return 0

    ps = ("$tr = New-ScheduledTaskTrigger -Daily -At '%s';"
          "Set-ScheduledTask -TaskName '%s' -Trigger $tr | Out-Null;"
          "$t = Get-ScheduledTask -TaskName '%s';"
          "Write-Output ('OK 下次运行 ' + ($t | Get-ScheduledTaskInfo).NextRunTime)"
          % (at, TASK, TASK))
    out = _ps(ps)
    print("[排程] " + (out or "设置完成(无回显)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
