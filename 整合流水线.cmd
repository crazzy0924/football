@echo off
rem 整合流水线任务入口 (22:10 触发: sky终盘 → 克劳德交叉 → 同路/分歧合并 → 渲染 → 推送)
cd /d %~dp0
python 整合流水线.py full >> 整合流水线.log 2>&1
