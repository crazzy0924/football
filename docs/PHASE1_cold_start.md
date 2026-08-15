# Phase 1 · 冷启动治理 — 实施规格
> 2026-08-14 · 基于代码审读 + 实盘数据验证 · 配套：docs/BASELINE_2026-08.md

## 问题定位（已验证，非推测）

### 现状链路
1. fetch_sporttery.py（体彩）：已正确生成标准 odds 字段（had → {home,draw,away}）——此前疑点排除
2. build_today_matches.py（odds-api.io v3 + Kambi）：odds 字段正确
3. pipeline.py predict：the-odds-api 合并（fetch_today_matches）—— 密钥有效但月度配额已耗尽（x-requests-remaining: 0，500/500 用尽），合并源失效
4. models/dixon_coles.py predict：冷启动 + 有市场赔率 → _market_implied_lambda KL 反推 λ（已验证生效：predictions_2026-08-13.json 中 cold_start_detail.market_informed=true，λ=1.06/0.98）
5. 冷启动 + 无市场赔率 → 联赛中位数先验（att/def≈1.0）→ 输出退化：OU25 撞车 0.588 常数（台账中 Mura/Silkeborg/CFR Cluj/Plymouth 等 8+ 场完全相同）

### 退化场次的来源（联赛覆盖缺口）
斯洛文尼亚/保加利亚/俄罗斯/丹麦/罗马尼亚/英格兰低级别/智利等——体彩不覆盖、the-odds-api 配额尽、odds-api.io 事件缺失 → 无任何赔率。

### 影响量化
- 08-11：9/12 冷启动（准确率 25%）；08-13：8/10（30%）——冷启动与无赔率高度重合
- 无赔率场次的预测无信息量，但仍计入 Brier/准确率统计 → 指标失真

## 修复方案（按优先级）

### A1. 赔率覆盖补充（数据层，改动最小）
- 主路径改走 odds-api.io v3：build_today_matches.py 已实现（events + Kambi odds，密钥实测有效），纳入每日流程
- pipeline/odds_fetcher.py 增加 odds-api.io 兜底（the-odds-api 配额耗尽时自动切换），并对 x-requests-remaining: 0 提前告警
- 体彩路径保持（中国竞彩唯一权威源）

### A2. 无赔率场次标记「无信号」并退出统计（统计口径，改动小）
- pipeline.py predict：无 odds 的场次 value=null 且冷启动 → 标记 no_signal: true
- review 时 no_signal 场次不计入 Brier/准确率（报告保留展示，单独列「无信号」分组）
- 验收：无信号场次占比报告化（当前估算 ~30%），指标反映真实技能

### A3. 训练库扩充缩小冷启动面（数据层，收益最大）
- h2h.py 全库（本地 ~3 万场，含 openfootball 三源）并入 data_loader.load_all_matches
- 预估训练量 26,663 → ~30,000+，冷启动球队数显著下降
- 验收：冷启动占比 <30%；同联赛冷启动场次用队史（同联赛同级别）先验

### A4. 冷启动先验升级（模型层，最后做）
- 联赛中位数 → ELO 分桶先验：按联赛 ELO 分布分 3-5 桶，冷启动球队取所在联赛同级球队中位 att/def
- 需训练期统计 ELO 分桶（trainer 增加一步），改动集中在 _get_league_medians

## 验收标准
1. 无赔率场次在报告中明确标记且不计入准确率
2. 冷启动占比从 ~44% 降至 <30%
3. 1X2 Brier < 0.2243（当前台账值），整体 Brier 较 0.2278 下降
4. 每日流程（A1）连续 3 天无人工干预跑通

## 执行顺序
A1（数据可用性）→ A2（指标诚实）→ A3（数据扩充）→ A4（先验升级），每步独立验证，通过门禁后进入下一步。
