# 公式参考手册

## 1. Shin 去水公式 (赔率→真实概率)

**问题**: 赔率不能直接 1/odds 当概率，因为有庄家抽水(margin)。
**公式**: Shin (1993) 模型，基于部分信息假设。

```
求解 z 满足: Σ sqrt(z·(1-z)/odds_i + (1-z)²) - (1-z) = 1
概率: P_i = sqrt(z·(1-z)/odds_i + (1-z)²) - (1-z)
margin = Σ(1/odds_i) - 1
```

**代码**: `src/models/odds_analyzer.py::_shin_method()` ✅ 已实现
**调用**: 每次 get_match_odds → calculate_implied_probability(method="shin")
**状态**: ⚠ 在 today_aug5_v1.html 中未调用, 用的还是 proportional 方法

---

## 2. 泊松进球模型 (Dixon-Coles 简化)

**公式**:
```
λ_home = baseline × attack_home × defense_away × exp(home_advantage)
λ_away = baseline × attack_away × defense_home
P(gh, ga) = Poisson(gh|λ_h) × Poisson(ga|λ_a)
```

**代码**: 所有预测引擎核心, 五底座(B0/B1+/B2-RC)共用
**状态**: ✅ 已实现
**缺失**: Dixon-Coles ρ 参数 (低比分修正) 尚未实现 ⚠

Dixon-Coles 完整版:
```
P(gh, ga) = τ(gh, ga) × Poisson(gh|λ_h) × Poisson(ga|λ_a)
τ(gh, ga) = 1 - λ·μ·ρ  if gh=0,ga=0
           = 1 + λ·ρ    if gh=0,ga=1
           = 1 + μ·ρ    if gh=1,ga=0
           = 1 - ρ      if gh=1,ga=1
           = 1           otherwise
```
ρ 参数修正了泊松对 0-0/1-0/0-1/1-1 的系统性低估。
**待实现** ⚠

---

## 3. 贝叶斯融合公式

**公式**:
```
Dirichlet 后验 = Dir(α_prior + α_evidence)
α_prior[i] = model_prob[i] × N     N = 10 + model_confidence × 50
α_evidence[i] = market_prob[i] × M  M = f(margin, dispersion)
posterior[i] = (α_prior[i] + α_evidence[i]) / (N + M)
```

**代码**: `src/models/bayesian.py::bayesian_update()` ✅
**状态**: 已实现但 ⚠ 在 today_aug5_v1.html 中未调用

---

## 4. 蒙特卡洛泊松模拟

**公式**:
```
goals_home ~ Poisson(λ_h)  × 10000 次采样
goals_away ~ Poisson(λ_a)  × 10000 次采样
P(结果) = count(结果) / 10000
95%CI = x̄ ± 1.96 × σ/√n
```

**代码**: `tools/simulate.py::simulate_match()` ✅
**状态**: ✅ 已实现, 在 predict_v2.html 中调用
**改进**: n_sims 已从10000→建议25000

---

## 5. xG 代理公式

**公式**:
```
xG_proxy = 射正数 × 0.28 + 射偏数 × 0.04 + 角球 × 0.02
         + (危险进攻/总进攻) × 0.5
xGA_proxy = xG_proxy × (0.7 + 0.3 × (1 - 控球率))
```

**代码**: `src/agent/tools.py::_compute_xg()` ✅
**状态**: ✅ 已实现, 在 calculate_recent_xg 工具中调用
**局限**: 代理xG ≠ 真实xG (真实xG需要射门位置/角度/身体部位等数据)

---

## 6. 凯利公式 (Kelly Criterion)

**公式**:
```
f* = (b × p - q) / b
b = 赔率 - 1 (净赔率)
p = 模型预测概率
q = 1 - p
保守: 1/4 Kelly = 0.25 × f*
```

**代码**: `src/models/odds_analyzer.py::_calc_kelly()` ✅
**状态**: ✅ 已实现

---

## 7. Brier Score (概率预测评分)

**公式**:
```
Brier = (1/n) × Σ[(p_home - a_home)² + (p_draw - a_draw)² + (p_away - a_away)²]
a = 实际结果向量 (1,0,0) / (0,1,0) / (0,0,1)
范围: 0~2, 越低越好。0.25=随机猜测, <0.20=优秀
```

**代码**: `src/models/evaluation.py::lockbox_evaluate()` ✅
**状态**: ✅ 已实现

---

## 8. Log Loss (对数损失)

**公式**:
```
LogLoss = -(1/n) × Σ ln(p_actual)
p_actual = 模型对实际发生结果的预测概率
越低越好, <0.90=优秀
```

**代码**: `src/models/evaluation.py` ✅
**状态**: ✅ 已实现

---

## 9. Herfindahl 集中度指数

**公式**:
```
H = Σ(p_i)²  对 i = 所有比分
H > 0.15 = 过度集中 (结构塌陷信号)
```

**代码**: `src/models/five_bases.py::_concentration()` ✅
**状态**: ✅ 已实现, 在五底座每次输出时检测

---

## 10. ELO 期望胜率公式

**公式**:
```
E_A = 1 / (1 + 10^((R_B - R_A) / 400))
主场: R_A += 主场加成 (CLQ=+60, 英超=+90, MLS=+130)
ELO更新: R'_A = R_A + K × (S_A - E_A) × 净胜球系数
K = 32, 净胜球系数: 差1球=1.0, 2球=1.5, 3球+=(11+diff)/8
```

**代码**: `src/models/elo.py` ✅
**状态**: ✅ 已实现

---

## 11. 贝叶斯赛中动态更新公式

**公式**:
```
P(终场胜 | 当前比分, 剩余分钟) ∝ P(当前比分 | 终场胜) × P(赛前胜)

P(当前比分 | 终场胜) = Poisson(gh|λ_h × t/90) × Poisson(ga|λ_a × t/90)
t = 已进行分钟数
```

**代码**: ❌ 未实现 — 仅在设计文档中提及
**状态**: ⚠ 待实现, 用于赛中滚球预测

---

## 12. 时间衰减权重

**公式**:
```
w(match) = exp(-λ × days_ago)
λ = 0.01 (半衰期约70天)
越近的比赛权重越高
```

**代码**: ❌ 未实现 — 仅在设计文档中提及
**状态**: ⚠ 待实现, 用于历史数据加权回归

---

## 13. 冷启动动态修正公式

**公式**:
```
修正量 = clamp((实际进球 - 预期进球) / max(预期, 0.5) × 0.10, -0.15, +0.15)
新攻击力 = max(0.5, 旧攻击力 + 修正量)
置信权重: 0.30 → 0.55 → 0.80 → 1.00 (每场递增)
```

**代码**: `src/models/cold_start.py::ColdStartEngine.update()` ✅
**状态**: ✅ 已实现

---

## 14. 联赛自适应λ公式

**公式**:
```
λ_home = (联赛场均总球/2) × attack_home × defense_away × (1 + 联赛主场加成)
联赛主场加成: CLQ=0.18, PL=0.28, MLS=0.40 (非通用0.30)
```

**代码**: `src/models/league_profiles.py::adaptive_params()` ✅
**状态**: ✅ 已实现, 但在 today_aug5_v1.html 中硬编码非动态加载

---

## ⚠ 待实现的公式

| 公式 | 影响 | 优先级 |
|------|------|:---:|
| **Dixon-Coles ρ 修正** | 泊松系统性低估 0-0/1-0/0-1/1-1 | 高 |
| **时间衰减权重** | 历史数据加权回归 | 中 |
| **贝叶斯赛中更新** | 滚球动态胜率 | 中 |
| **Shin方法整合到HTML** | 当前HTML用proportional非Shin | 高 |

---

## ✅ 检查清单: today_aug5_v1.html 中实际调用了哪些公式?

| 公式 | 是否调用 |
|------|:---:|
| 泊松进球模型 | ✅ |
| ELO期望胜率 | ✅ |
| 蒙特卡洛(n=10000) | ✅ |
| 联赛自适应λ (硬编码) | ✅ |
| 贝叶斯融合 | ❌ 未调用 |
| Shin去水 | ❌ 用的是proportional |
| Herfindahl集中度检测 | ❌ 未调用 |
| 凯利公式 | ❌ 未调用 |
| 五底座并行 | ❌ 未调用 |
| 基线对比 | ❌ 未调用 |
| 锁箱评估 | ❌ 未调用 |
| 冷启动 | ❌ 未调用 |
| 蒸汽移动检测 | ❌ 缺早盘基准 |
| Dixon-Coles ρ | ❌ 未实现 |
| 时间衰减 | ❌ 未实现 |

**结论: today_aug5_v1.html 只用了核心泊松+ELO引擎，后端新增的10个公式(Shin/贝叶斯/五底座/基线/锁箱/冷启动/凯利/集中度/蒸汽移动/时间衰减)均未接入前端HTML。**
