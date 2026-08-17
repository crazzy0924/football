@echo off
rem 终盘任务入口 (22:00 触发: 注入早午盘存档 → 终盘预测+七维分析 → 唯一出预测的页面; 全量体彩比赛)
cd /d %~dp0
python daily_run.py predict --stage final --all-leagues >> data\log\final_predict.log 2>&1
