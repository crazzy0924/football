# -*- coding: utf-8 -*-
"""国家队侧的模型×市场融合 —— 显式对数意见池, 不用俱乐部那套贝叶斯。

为什么不用 models/bayesian.bayesian_fusion_predict (2026-09-24 踩到的坑):
  它的市场证据强度 M 由 **赔率抽水**驱动: margin_factor = 0.02/margin。
  俱乐部链路喂的是 Pinnacle (抽水 2-3%), 所以"M 大 = 信市场"成立。
  但国家队侧唯一可得的市场是**体彩竞彩**, 抽水约 13%。
  那不是"市场不确定", 那只是**价格加成** —— 去水之后的概率依然是有信息量的。
  直接套用会把市场权重压到 29%、模型推到 71%, 等于让一个**从未与市场做过
  配对检验**的模型去否决市场。这是纪律问题, 不是调参问题。

所以这里改用对数意见池 (logarithmic opinion pool):
    p_i ∝ p_model_i ** w  *  p_market_i ** (1 - w)
w 显式写死, 可解释、可审计, 不随抽水漂移。

w 的取值纪律:
  在拿到足够多的"模型预测 + 同期赔率 + 赛果"之前, w 只能是猜的。
  2026/27 欧国联 League A 联赛阶段共 6 轮 × 8 场 = 48 场, 打完就有 48 个样本,
  那时才够跑一次配对检验来定 w。在那之前固定 0.20 (市场主导)。
"""

DEFAULT_MODEL_WEIGHT = 0.20


def log_opinion_pool(model_probs, market_probs, w: float = DEFAULT_MODEL_WEIGHT):
    """w 为模型的权重 (0 = 全听市场, 1 = 全听模型)。"""
    import math
    w = max(0.0, min(1.0, float(w)))
    out = []
    for pm, pk in zip(model_probs, market_probs):
        pm = max(float(pm), 1e-9)
        pk = max(float(pk), 1e-9)
        out.append(math.exp(w * math.log(pm) + (1.0 - w) * math.log(pk)))
    s = sum(out)
    return [x / s for x in out]