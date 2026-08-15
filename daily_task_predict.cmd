@echo off
rem 每日预测计划任务入口 (09:00 触发)
cd /d D:\足球大模型1.0
python daily_run.py predict >> data\log\daily_predict.log 2>&1
