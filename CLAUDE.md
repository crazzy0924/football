# 工作纪律 · v3.0 Pipeline

## 强制规则 (违反=偷懒)

### 每次生成预测后必须:

1. ✅ 更新 `archive.html` — 在对应日期下追加预测和复盘链接
2. ✅ `git add -A && git commit -m "说明" && git push origin master`
3. ✅ 确认 push 成功才结束任务

### 每次复盘必须:

1. ✅ 如实报告命中率，不编造不美化
2. ✅ 数字一字不改 — Brier/Accuracy/ROI 从 review 命令输出直接抄
3. ✅ ELO 更新确认：review 命令自动更新，验证 state 文件已保存

### 每次预测必须包含:

1. ✅ 模型输出: Dixon-Coles 胜平负概率 + 贝叶斯后验 + Kelly 值
2. ✅ 市场对比: 模型 vs 市场 edge 检测
3. ✅ 冷启动标记: 数据不足的场次标注 COLD START

## v3.0 每日操作

```bash
# 1. 获取今日比赛 (JSON格式，含赔率)
python pipeline.py predict --matches-json data/today.json

# 2. 查看预测报告
# data/output/predictions_YYYY-MM-DD.html

# 3. 比赛结束后 — 复盘
python pipeline.py review YYYY-MM-DD --results-text "TeamA 2-1 TeamB\n..."
# 或: echo '[{"home_team":"A","away_team":"B","home_goals":2,"away_goals":1}]' > data/output/results_DATE.json
# python pipeline.py review YYYY-MM-DD

# 4. 查看复盘报告
# data/output/review_YYYY-MM-DD.html
```

## 模型门禁 (硬性)

- 回测 Brier < 基线 Brier (0.65) → PASS ✅ (当前 0.60)
- 回测未通过 → 禁止上线，修复模型后重试
- `python pipeline.py backtest` 验证

## 深盘规则 (v2.0 教训，v3.0 继承)

v2.0 中 5场让球>1.0深盘仅1场穿盘，经验保留：
- ELO差>200 + 联赛场均进球<2.5 → 深盘(>1.5)自动降一档
- 参考联赛风格: 克罗地亚/波兰/捷克 → 天然小球
- 赔率以实时数据为准，不依赖搜索缓存

## 克劳德独立分析师 (Phase 4)

`--llm` flag 启用后:
- Claude 收到结构化证据包 (ELO, DC概率, 联赛画像)
- 只做定性评估: 伤停/战意/杯赛阶段等模型盲区
- 不碰数字，不生成概率
- 标注 "分析师注释(LLM)" 与模型输出明确区分
- API不可用时预测正常运行

## 技术债务

- ~~scipy MLE~~ ✅ 已装 (scipy 1.18.0, L-BFGS-B + 解析梯度, 365次迭代收敛, Brier改善~0.002-0.007)
- MLE改善幅度小于预期: 回测Brier ~0.634 (baseline ~0.651), 距0.60目标仍有差距
- Phase 4 LLM 集成待实现
- odds-api.io 实时赔率拉取有时 GBK 编码问题 (Windows终端)
- 下一步可探索: 动态市场权重、近期状态因子、冷启动改进
