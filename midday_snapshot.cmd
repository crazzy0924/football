@echo off
rem 午盘赔率快照任务入口 (18:00 触发)
cd /d %~dp0
python fetch_sporttery.py >> data\log\midday_snapshot.log 2>&1
