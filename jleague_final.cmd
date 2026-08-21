@echo off
rem 日职终盘任务入口 (17:00 触发: 日职18:00开球前1小时出终盘, 含当日全部未开球场次)
cd /d %~dp0
python daily_run.py predict --stage final --all-leagues >> data\log\jleague_final.log 2>&1
