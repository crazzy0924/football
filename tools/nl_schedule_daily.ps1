# 每日 08:05: 给欧国联排当天的终盘任务 (有赛程才排, 无赛程静默)
#
# ⚠️ 本文件必须以 **UTF-8 with BOM** 保存 (2026-09-30 修):
#    Windows PowerShell 5.1 读无 BOM 的 .ps1 时按**系统 ANSI(GBK)** 解析,
#    路径里的中文会变成乱码 → Set-Location 失败 → 脚本继续往下跑还是 exit 0,
#    于是任务**看起来成功**(LastTaskResult=0), 实际什么都没排 —— 沉默失败 3 天。
#    这就是"比赛都不出了"的根因: 9/29 那 7 场根本没排终盘任务。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
if (-not (Test-Path $root)) { throw "找不到项目根目录: $root" }
Set-Location -LiteralPath $root

$log = Join-Path $root 'data\log\nl_schedule.log'
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data\log') | Out-Null
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 每日排程检查 (root=$root) ===" |
    Out-File -FilePath $log -Append -Encoding utf8

# 用完整路径调 python, 不依赖 PATH
$py = 'C:\Python314\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

& $py (Join-Path $root 'tools\schedule_nl.py') 2>&1 |
    Out-File -FilePath $log -Append -Encoding utf8

# 校验: 若今天有赛程却没排上任务, 必须留下痕迹 (不能静默)
$nl = & $py -c "import sys; sys.path.insert(0, r'$root'); from datetime import datetime; from national.run_nl import fetch_sporttery, kickoff_abs; d=datetime.now().strftime('%Y-%m-%d'); rows=[m for m in fetch_sporttery() if '欧国联' in (m.get('league') or '') and (m.get('business_date') or '')==d]; print(len(rows))" 2>$null
"[检查] 今天比赛日欧国联场次 = $nl" | Out-File -FilePath $log -Append -Encoding utf8
if ($nl -and [int]$nl -gt 0) {
    $has = Get-ScheduledTask -TaskName '足球模型-欧国联终盘' -ErrorAction SilentlyContinue
    if (-not $has) {
        "[❌] 有 $nl 场欧国联, 但终盘任务不存在 —— 请人工检查" | Out-File -FilePath $log -Append -Encoding utf8
        exit 3
    }
    $nrt = ($has | Get-ScheduledTaskInfo).NextRunTime
    "[✔] 终盘任务已排: 下次运行 $nrt" | Out-File -FilePath $log -Append -Encoding utf8
}
exit 0
