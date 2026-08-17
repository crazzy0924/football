@echo off
rem 早盘任务入口 (09:00 触发: 拉赔率+伤停+积分榜 → 早盘七维分析存档, 不出预测)
cd /d %~dp0
python daily_run.py predict --stage morning >> data\log\daily_predict.log 2>&1
