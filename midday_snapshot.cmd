rem 午盘任务入口 (18:00 触发: 最新赔率重跑七维分析 → 午盘存档, 不出预测; 只做五大联赛)
cd /d %~dp0
python daily_run.py predict --stage midday >> data\log\midday_snapshot.log 2>&1
