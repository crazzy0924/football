# -*- coding: utf-8 -*-
"""欧国联「终盘」排程 (2026-09-26 用户拍板: 给欧国联配自己的排程)

为什么要有这个文件
------------------
9/26 的教训: 终盘那套 (tools/schedule_final.py) 是**竞彩五大+欧冠**的 —— 当天
「无五大+欧冠场次」就整体跳过; 而欧国联**根本不进竞彩**(today.json = 0 场),
于是 21:00/22:00 的临场水位永远进不来, E 盘 nl_cross 一直判"同一版赔率已出稿"。
结果: 那 7 场用的全是 16:37 那一版赔率, 21:00 之后没有任何一版。

规则 (用户拍板)
--------------
    终盘时刻 = **当日最早开赛前 45 分钟** (LEAD_MIN)
    只算**体彩比赛日 = 今天**的欧国联场次 (含凌晨场; 比赛日 D 覆盖 D 白天 → D+1 早上)
    没有场次 → 不排、不报警 (「当天无赛程」是一等公民状态)
    目标时刻已过 → 不排, 只提示手工补

任务 (trigger 用 -Once, 不是 -Daily —— 比赛日是零散的)
    动作 = 赔率刷新(B轨) → 终盘模式八维(A轨, 复用第一段盲判) → 出页
    动作里**钉死 --date** (终盘常在午夜后触发, 不钉会拉错一天)

用法
----
    python tools/schedule_nl.py                  # 按今天算并写入计划任务
    python tools/schedule_nl.py --dry-run        # 只看会排到几点
    python tools/schedule_nl.py --date 2026-10-09
    python tools/schedule_nl.py --check          # 只校验当前任务状态
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK = "足球模型-欧国联终盘"

# === 终盘时刻规则 (2026-09-26 用户拍板, 写死) ===
LEAD_MIN = 45          # 终盘 = 最早开赛前 N 分钟
LOG = r"data\log\nl_final.log"
MAX_HOURS = 2          # 执行时限


def _ps(cmd: str) -> str:
    """执行 PowerShell —— 写临时 .ps1 (UTF-8 BOM) 再跑。

    不用 -Command/-EncodedCommand: 设任务**动作**时参数里带引号与 && >> 重定向,
    走命令行会被打散, Set-ScheduledTask 会**静默失败** (2026-09-18 实测)。
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
            return "ERR " + err[:300]
        return out
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def load_nl(date_str: str):
    """取体彩在售的欧国联场次 → [(开赛绝对时间, 场次dict)]，按时间排序。"""
    sys.path.insert(0, ROOT)
    from national.run_nl import fetch_sporttery, kickoff_abs
    rows = []
    for m in fetch_sporttery():
        if "欧国联" not in (m.get("league") or ""):
            continue
        if (m.get("business_date") or "") != date_str:
            continue          # 只算**今天这个比赛日**的场次
        ko = kickoff_abs(m["business_date"], m["match_time"])
        if ko is None:
            print("   ⚠ 读不到开赛时间, 跳过: %s vs %s (%r)"
                  % (m.get("home_cn"), m.get("away_cn"), m.get("match_time")))
            continue
        rows.append((ko, m))
    rows.sort(key=lambda x: x[0])
    return rows


def plan(date_str: str, rows=None):
    """→ (目标时刻 或 None, 原因字符串)；rows 可注入 (自测用, 免联网)"""
    rows = load_nl(date_str) if rows is None else rows
    if not rows:
        return None, "比赛日 %s 没有欧国联场次" % date_str
    now = datetime.now()
    upcoming = [(dt, m) for dt, m in rows if dt > now]
    print("[欧国联排程] 比赛日 %s: 在售 %d 场, 未开赛 %d 场" % (date_str, len(rows), len(upcoming)))
    for dt, m in rows[:8]:
        print("   %s  %-6s %s vs %s  [%s]" % (
            dt.strftime("%m-%d %H:%M"), m.get("num"), m.get("home_cn"), m.get("away_cn"),
            "未开赛" if dt > now else "已开赛"))
    if not upcoming:
        return None, "所有场次都已开赛 → 不排终盘"
    first = upcoming[0][0]
    target = first - timedelta(minutes=LEAD_MIN)
    print("[欧国联排程] 最早开赛 %s → 终盘 = 提前 %d 分钟 = %s" % (
        first.strftime("%m-%d %H:%M"), LEAD_MIN, target.strftime("%m-%d %H:%M")))
    return target, "ok"


def action_cmd(date_str: str) -> str:
    """任务动作: 赔率刷新(B轨) → 终盘模式八维(A轨) → 出页。"""
    return ('/c cd /d "%s" && '
            'python national\\run_nl.py --date %s >> %s 2>&1 && '
            'python national\\octa.py --date %s --final --include-started >> %s 2>&1 && '
            'python national\\make_page.py --date %s >> %s 2>&1') % (
        ROOT, date_str, LOG, date_str, LOG, date_str, LOG)


def set_task(target: datetime, date_str: str) -> int:
    at = target.strftime("%Y-%m-%dT%H:%M:00")
    arg = action_cmd(date_str)
    ps = ("$tr = New-ScheduledTaskTrigger -Once -At ([datetime]'%s');"
          "$ac = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '%s';"
          "$st = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours %d) "
          "-StartWhenAvailable -MultipleInstances IgnoreNew;"
          "Register-ScheduledTask -TaskName '%s' -Trigger $tr -Action $ac -Settings $st "
          "-Force -Description '欧国联终盘: 最早开赛前 %d 分钟, 刷新赔率+重出判断(复用第一段盲判)' | Out-Null"
          % (at, arg, MAX_HOURS, TASK, LEAD_MIN))
    out = _ps(ps)
    if out.startswith("ERR"):
        print("[欧国联排程] ❌ 写任务失败: %s" % out)
        return 3
    return verify(target, date_str)


def verify(target: datetime, date_str: str = "") -> int:
    """改完当场读回校验 —— 不对就报警退出码 3。"""
    ps = ("$t = Get-ScheduledTask -TaskName '%s';"
          "$i = $t | Get-ScheduledTaskInfo;"
          "$a = $t.Actions | Select-Object -First 1;"
          "Write-Output ('NEXT=' + $i.NextRunTime.ToString('yyyy-MM-ddTHH:mm:ss'));"
          "Write-Output ('NTRIG=' + $t.Triggers.Count);"
          "Write-Output ('ACTION=' + $a.Arguments)" % TASK)
    raw = _ps(ps)
    vals = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    try:
        nxt = datetime.strptime(vals.get("NEXT", "")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        print("[校验] ❌ 读不回下次运行时间 (回显: %r)" % raw)
        return 3

    print("[校验] 下次运行 %s | 触发器数 %s" % (nxt.strftime("%m-%d %H:%M"), vals.get("NTRIG", "?")))
    problems = []
    if abs((nxt - target).total_seconds()) > 120:
        problems.append("与目标 %s 不符 (差 %.0f 分钟)" % (
            target.strftime("%m-%d %H:%M"), (nxt - target).total_seconds() / 60))
    if vals.get("NTRIG") not in ("1", "?"):
        problems.append("触发器不是 1 个 (=%s)" % vals.get("NTRIG"))
    if date_str and ("--date %s" % date_str) not in (vals.get("ACTION") or ""):
        problems.append("动作里没钉住 --date %s" % date_str)
    if nxt <= datetime.now():
        problems.append("下次运行时间已过期")
    if (nxt - datetime.now()).total_seconds() > 30 * 86400:
        problems.append("超过 30 天才跑 —— 很可能起始时间设在过去被跳过了")
    if problems:
        for p in problems:
            print("[校验] ❌ %s" % p)
        return 3
    print("[校验] ✅ 通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="",
                    help="体彩比赛日; 留空 = 按当前时刻推算 (12:00 前算前一天)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="只校验当前任务, 不修改")
    ap.add_argument("--clear", action="store_true", help="删除该任务 (今天没有欧国联时用)")
    a = ap.parse_args()

    if not a.date:
        # 2026-09-30 加: 不能用 datetime.now().date()。体彩比赛日 D 覆盖 D 白天 → D+1 早上,
        # 所以 12:00 前算**前一天**。起因: 若每日排程任务被 StartWhenAvailable 补跑在凌晨,
        # 用"今天"会去查明天的赛程, 当晚这批凌晨场就永远排不上 (与 pipeline.py 同一条规则)。
        a.date = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d")
        print("[欧国联排程] 未指定 --date → 按当前时刻推算比赛日 = %s" % a.date)

    if a.clear:
        out = _ps("Unregister-ScheduledTask -TaskName '%s' -Confirm:$false" % TASK)
        print("[欧国联排程] 已尝试删除任务: %s" % (out or "OK"))
        return 0

    target, why = plan(a.date)
    if target is None:
        print("[欧国联排程] %s → 不安排" % why)
        print("           需要临时出终盘: python national\\octa.py --date %s --final --include-started"
              % a.date)
        return 2
    if a.check:
        return verify(target, a.date)
    if target <= datetime.now():
        print("[欧国联排程] 目标时刻 %s 已过 (现在 %s) → 不安排"
              % (target.strftime("%m-%d %H:%M"), datetime.now().strftime("%m-%d %H:%M")))
        print("           要立刻补一版: python national\\octa.py --date %s --final --include-started"
              % a.date)
        return 2
    if a.dry_run:
        print("[欧国联排程] --dry-run: 本应把「%s」设为 %s 一次性触发"
              % (TASK, target.strftime("%Y-%m-%d %H:%M")))
        print("           动作: %s" % action_cmd(a.date))
        return 0
    return set_task(target, a.date)


if __name__ == "__main__":
    raise SystemExit(main())
