# 每日 08:05: 给欧国联排当天的终盘任务 (有赛程才排, 无赛程静默)
# 由 tools/schedule_nl.py 用 --install-daily 写入, 也可手工建。
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location 'D:\足球大模型1.0'
New-Item -ItemType Directory -Force -Path 'data\log' | Out-Null
$log = 'data\log\nl_schedule.log'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 每日排程检查 ===" | Out-File -FilePath $log -Append -Encoding utf8
& python tools\schedule_nl.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
exit 0
