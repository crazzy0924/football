@echo off
rem 每日复盘计划任务入口 (21:30 触发)
cd /d D:\足球大模型1.0
python daily_run.py review >> data\log\daily_review.log 2>&1
