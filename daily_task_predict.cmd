@echo off
rem 每日预测计划任务入口 (09:00 触发)
cd /d %~dp0
python daily_run.py predict >> data\log\daily_predict.log 2>&1
