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

# === 终盘时刻规则 (用户拍板 2026-09-19, 写死) ===
#   默认 21:00; 当日比赛日的场次里有开赛早于 21:00 的 → 提前到 20:00。
DEFAULT_AT = (21, 0)        # 默认出终盘的时刻 (时, 分)
EARLY_AT = (20, 0)          # 有早场时提前到的时刻
EARLY_BEFORE_HOUR = 21      # "早场"的判定线: 开赛时间早于这个整点


def _ps(cmd: str) -> str:
    """执行 PowerShell —— 写临时 .ps1 (UTF-8 BOM) 再跑。

    不用 -Command/-EncodedCommand (2026-09-18 实测): 设置任务的**动作**时参数里带
    双引号和 && >> 重定向, 走命令行会被打散, Set-ScheduledTask 静默失败 ——
    表现为"触发时间设对了, 但动作没换", 而且不报错。写文件执行没有这个问题。
    """
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    try:
        with io.open(path, "w", encoding="utf-8-sig") as f:
            f.write(cmd)
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if err and not out:
            return "ERR " + err[:200]
        return out
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


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
    ap.add_argument("--check", action="store_true",
                    help="只校验当前任务状态, 不修改")
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
    # === 终盘时刻规则 (用户拍板 2026-09-19, 写死) ===
    #   默认: 每天 21:00 出终盘
    #   若当日比赛日的场次里, 有开赛时间早于 21:00 的 → 提前到 20:00
    # 只有两条分支, 不再算"最早开赛前90分钟"那种动态时点。
    early = [(dt, m) for dt, m in rows if dt.hour < EARLY_BEFORE_HOUR]
    hh, mm = (EARLY_AT if early else DEFAULT_AT)
    target = datetime.strptime(a.date, "%Y-%m-%d").replace(hour=hh, minute=mm, second=0, microsecond=0)
    print()
    print("[排程] 规则: 默认 %02d:%02d; 有早于 %02d:00 开赛的场次则 %02d:%02d" % (
        DEFAULT_AT[0], DEFAULT_AT[1], EARLY_BEFORE_HOUR, EARLY_AT[0], EARLY_AT[1]))
    print("[排程] 当日早于 %02d:00 开赛的场次: %d 场 → 终盘定在 %s" % (
        EARLY_BEFORE_HOUR, len(early), target.strftime("%m-%d %H:%M")))
    for dt, m in early[:4]:
        print("       早场 %s %s vs %s" % (
            dt.strftime("%m-%d %H:%M"), m.get("home_team", ""), m.get("away_team", "")))

    if not upcoming:
        print()
        print("[排程] 今天没有未开赛的场次 → 不安排终盘")
        print("       需要临时出终盘: python daily_run.py predict --stage final --force")
        return 2

    if a.check:
        return _verify(target)

    if target <= now:
        print("[排程] 目标时刻已过 (现在 %s) → 不安排" % now.strftime("%H:%M"))
        print("       需要立即出终盘: python daily_run.py predict --stage final --force")
        return 2

    at = target.strftime("%Y-%m-%dT%H:%M:00")
    if a.dry_run:
        print("[排程] --dry-run: 本应把任务设为每天 %s 触发" % target.strftime("%H:%M"))
        return 0

    # 动作里必须钉死 --date (2026-09-18 修):
    # 终盘常在**午夜后**触发(如 01:00), 那时 daily_run 的 date_str 取"今天"已经翻到
    # 次日 → 会去拉**下一天**的比赛日, 给出错误一天的终盘。实测 09-18 这批 5 场
    # (开赛 09-19 凌晨) 属于比赛日 09-18, 必须显式传 --date 2026-09-18。
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    arg = ('/c cd /d "%s" && python daily_run.py predict --stage final --date %s '
           '>> data' + chr(92) + 'log' + chr(92) + 'final_predict.log 2>&1' % (root, a.date))
    ps = ("$tr = New-ScheduledTaskTrigger -Daily -At '%s';"
          "$ac = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '%s';"
          "Set-ScheduledTask -TaskName '%s' -Trigger $tr -Action $ac | Out-Null"
          % (at, arg, TASK))
    _ps(ps)
    return _verify(target, a.date)


def _verify(target: datetime, date_str: str = "") -> int:
    """改完立刻读回任务状态并校验 —— 2026-09-18 加。

    起因: 手动改任务时把起始时间设成**过去**的时刻, Windows 把下一次算成了后天,
    直接跳过了一整天的复盘, 而当时没有任何检查发现。人改任务状态必须当场验证。
    """
    ps = ("$t = Get-ScheduledTask -TaskName '%s';"
          "$g = $t.Triggers[0];"
          "$i = $t | Get-ScheduledTaskInfo;"
          "$a = $t.Actions | Select-Object -First 1;"
          "Write-Output ('NEXT=' + $i.NextRunTime.ToString('yyyy-MM-ddTHH:mm:ss'));"
          "Write-Output ('INTERVAL=' + $g.DaysInterval);"
          "Write-Output ('REPEAT=' + $g.Repetition.Interval);"
          "Write-Output ('ACTION=' + $a.Arguments)"
          % TASK)
    raw = _ps(ps)
    vals = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()

    nxt = vals.get("NEXT", "")
    try:
        nxt_dt = datetime.strptime(nxt[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        print("[校验] ❌ 读不回下次运行时间 (回显: %r)" % raw)
        return 3

    now = datetime.now()
    print("[校验] 下次运行 %s | 每天间隔 %s | 重复窗口 %r" % (
        nxt_dt.strftime("%m-%d %H:%M"), vals.get("INTERVAL", "?"),
        vals.get("REPEAT", "")))

    problems = []
    if nxt_dt <= now:
        problems.append("下次运行时间已过期")
    if abs((nxt_dt - target).total_seconds()) > 120:
        problems.append("与目标 %s 不符 (差了 %.0f 分钟)" % (
            target.strftime("%m-%d %H:%M"), (nxt_dt - target).total_seconds() / 60))
    if (nxt_dt - now).total_seconds() > 48 * 3600:
        problems.append("超过 48 小时才跑 —— 很可能是起始时间设在过去, 被跳过了一整天")
    if vals.get("INTERVAL") not in ("1", "?"):
        problems.append("不是每天一次 (间隔=%s)" % vals.get("INTERVAL"))
    if vals.get("REPEAT"):
        problems.append("残留重复窗口 %s" % vals.get("REPEAT"))
    # 动作必须钉死比赛日 (2026-09-18 加): 终盘常在午夜后跑, 不带 --date 就会拉错一天。
    act = vals.get("ACTION", "")
    if date_str:
        if ("--date " + date_str) not in act:
            problems.append("动作里没有 --date %s (午夜后跑会拉错比赛日)" % date_str)
    elif "--date" not in act:
        problems.append("动作里没有 --date")

    if problems:
        print("")
        print("=" * 62)
        print("[校验] ❌ 任务状态不对:")
        for p in problems:
            print("       - " + p)
        print("       请检查: Get-ScheduledTask -TaskName '%s'" % TASK)
        print("=" * 62)
        return 3
    print("[校验] ✅ 任务状态正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
