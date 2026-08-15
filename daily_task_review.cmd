@echo off
rem 每日复盘计划任务入口 (21:30 触发)
cd /d %~dp0
python daily_run.py review >> data\log\daily_review.log 2>&1
