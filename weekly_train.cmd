@echo off
rem 每周重训任务入口 (周一 06:00 触发)
cd /d %~dp0
python pipeline.py train >> data\log\weekly_train.log 2>&1
python pipeline.py backtest >> data\log\weekly_train.log 2>&1
python daily_run.py predict --no-llm >> data\log\weekly_train.log 2>&1
