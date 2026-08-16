@echo off
rem 终盘预测任务入口 (22:00 触发: 最新赔率重跑预测+七维分析)
cd /d %~dp0
python daily_run.py predict >> data\log\final_predict.log 2>&1
