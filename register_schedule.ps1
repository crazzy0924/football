# 注册每日计划任务 (当前用户, 无需管理员)
$project = 'D:\足球大模型1.0'
New-Item -ItemType Directory -Force -Path (Join-Path $project 'data\log') | Out-Null
schtasks /Create /F /TN '足球模型-每日预测' /SC DAILY /ST 09:00 /TR "$project\daily_task_predict.cmd"
schtasks /Create /F /TN '足球模型-每日复盘' /SC DAILY /ST 10:00 /TR "$project\daily_task_review.cmd"
Write-Output '--- 已注册任务 ---'
schtasks /Query /TN '足球模型-每日预测' /FO LIST | Select-String 'TaskName|Next Run Time|Status'
schtasks /Query /TN '足球模型-每日复盘' /FO LIST | Select-String 'TaskName|Next Run Time|Status'
Write-Output '删除: schtasks /Delete /TN 足球模型-每日预测 /F  (复盘同理)'
