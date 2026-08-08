"""
赔率分析模块

核心功能:
1. 欧赔 → 隐含概率 (margin 剥离)
2. 必发指数 (Betfair Index) 计算
3. 模型预测 vs 市场赔率对比 → 价值检测
4. 凯利值 (Kelly Criterion) 投注建议

原理:
  庄家赔率含 margin (overround), 需先剥离再对比。
  必发指数反映真实资金流向, 与庄家赔率互补。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 数据结构
# ============================================================

@dataclass
class OddsLine:
    """单条赔率"""
    bookmaker: str           # e.g. "Bet365", "Betfair"
    home: float              # 主胜赔率
    draw: float              # 平局赔率
    away: float              # 客胜赔率
    updated: str = ""        # 更新时间
    is_exchange: bool = False  # 是否为交易所赔率


@dataclass
class ImpliedProbability:
    """剥离 margin 后的真实隐含概率"""
    home: float
    draw: float
    away: float
    margin: float            # 庄家抽水率 (overround - 1)
    method: str = "proportional"  # proportional | shin | basic


@dataclass
class BetfairIndex:
    """必发指数

    必发 (Betfair) 是全球最大的博彩交易所, 其指数反映:
    - 资金流向: 挂在某结果上的成交量占比
    - 市场情绪: 买方 vs 卖方挂单量
    - 冷热指数: 高指数 = 市场热捧, 低指数 = 市场看衰
    """
    home_index: float        # 主胜必发指数 (0-100)
    draw_index: float        # 平局必发指数 (0-100)
    away_index: float        # 客胜必发指数 (0-100)
    total_volume: float = 0  # 总成交量 (如果可获得)
    source: str = ""         # 数据来源


@dataclass
class ValueDetection:
    """价值投注检测"""
    home_value: float        # 模型概率 - 市场隐含概率 (正值 = 有价值)
    draw_value: float
    away_value: float
    best_value: str          # "home" | "draw" | "away" | "none"
    kelly_fraction: float    # 凯利投注比例 (0 = 不下注, 0.25 = 1/4 凯利)
    confidence: str          # "高" | "中" | "低" | "无"


@dataclass
class OddsComparison:
    """完整的赔率对比分析"""
    fixture_id: int | None = None
    home_team: str = ""
    away_team: str = ""

    # 欧赔平均
    avg_odds: OddsLine | None = None
    best_odds: OddsLine | None = None   # 最佳赔率 (最高)
    bookmaker_count: int = 0

    # 隐含概率
    implied: ImpliedProbability | None = None

    # 必发指数
    betfair_index: BetfairIndex | None = None

    # 模型预测概率
    model_home: float = 0.0
    model_draw: float = 0.0
    model_away: float = 0.0

    # 价值检测
    value: ValueDetection | None = None

    # 原始赔率表 (全部博彩公司)
    odds_table: list[OddsLine] = field(default_factory=list)


# ============================================================
# 赔率 → 隐含概率 (Margin 剥离)
# ============================================================

def calculate_implied_probability(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    method: str = "proportional",
) -> ImpliedProbability:
    """从赔率计算真实隐含概率

    博彩公司赔率包含 margin (overround), 不能直接取倒数。
    需要用数学方法剥离 margin, 还原为真实概率估计。

    Args:
        odds_home: 主胜赔率 (欧赔十进制)
        odds_draw: 平局赔率
        odds_away: 客胜赔率
        method:    margin 剥离方法
                   - "proportional": 比例分配 (最常用)
                   - "shin":         Shin 模型 (更精确)
                   - "basic":        直接归一化

    公式 (Proportional):
        overround = 1/odds_home + 1/odds_draw + 1/odds_away
        prob_home = (1 / odds_home) / overround
        prob_draw = (1 / odds_draw) / overround
        prob_away = (1 / odds_away) / overround
        margin = overround - 1.0

    示例:
        赔率 2.00 / 3.50 / 4.00
        overround = 0.50 + 0.286 + 0.25 = 1.036
        margin = 3.6%
        prob = 48.3% / 27.6% / 24.1%
    """
    if odds_home <= 1.0 or odds_draw <= 1.0 or odds_away <= 1.0:
        return ImpliedProbability(home=0, draw=0, away=0, margin=0)

    inv_home = 1.0 / odds_home
    inv_draw = 1.0 / odds_draw
    inv_away = 1.0 / odds_away
    overround = inv_home + inv_draw + inv_away

    if method == "shin":
        # Shin 模型: 假设庄家对每匹马 (每个结果) 设置相同的 margin
        # 通过迭代求解 z (Shin 参数), 更精确但更复杂
        prob_home, prob_draw, prob_away, margin = _shin_method(
            odds_home, odds_draw, odds_away
        )
        return ImpliedProbability(
            home=round(prob_home, 4),
            draw=round(prob_draw, 4),
            away=round(prob_away, 4),
            margin=round(margin, 4),
            method="shin",
        )

    # Proportional (默认)
    prob_home = inv_home / overround
    prob_draw = inv_draw / overround
    prob_away = inv_away / overround
    margin = overround - 1.0

    return ImpliedProbability(
        home=round(prob_home, 4),
        draw=round(prob_draw, 4),
        away=round(prob_away, 4),
        margin=round(margin, 4),
        method=method,
    )


def _shin_method(o1: float, o2: float, o3: float) -> tuple[float, float, float, float]:
    """Shin (1993) 模型剥离 margin

    Shin 模型假设庄家对每个结果应用相同的 uncertainty margin。
    通过求解 z 使得 Σ sqrt(z / odds_i) = 1

    对于 3-way 市场:
    prob_i = sqrt(z * (1 - z) / odds_i + (1 - z)**2) - (1 - z)
    """
    # 简化版: 二分搜索 z
    lo, hi = 0.0, 0.5
    for _ in range(50):
        z = (lo + hi) / 2
        s = sum(1.0 / o for o in [o1, o2, o3])
        # 用 approximation
        sum_term = 0.0
        for o in [o1, o2, o3]:
            term = (z * (1 - z)) / o + (1 - z) ** 2
            if term > 0:
                sum_term += term ** 0.5 - (1 - z)
        if sum_term > 1.0:
            hi = z
        else:
            lo = z

    z = (lo + hi) / 2
    probs = []
    for o in [o1, o2, o3]:
        term = (z * (1 - z)) / o + (1 - z) ** 2
        if term > 0:
            p = term ** 0.5 - (1 - z)
        else:
            p = 0.0
        probs.append(max(0.0, p))

    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]

    overround = sum(1.0 / o for o in [o1, o2, o3])
    margin = overround - 1.0

    return probs[0], probs[1], probs[2], margin


# ============================================================
# 必发指数计算
# ============================================================

def calculate_betfair_index(
    home_volume: float = 0,
    draw_volume: float = 0,
    away_volume: float = 0,
    home_back: float = 0,
    home_lay: float = 0,
    draw_back: float = 0,
    draw_lay: float = 0,
    away_back: float = 0,
    away_lay: float = 0,
) -> BetfairIndex:
    """计算必发指数

    必发指数 = (某结果成交量 / 总成交量) × 100

    当无法获取真实成交量时，用挂单量 (back + lay 的挂单总额) 作为代理。

    Args:
        home_volume: 主胜已成交量
        draw_volume: 平局已成交量
        away_volume: 客胜已成交量
        home_back/lay: 当前挂单量 (back=买入/看好, lay=卖出/看衰)

    解读:
        - 指数 > 50: 资金大幅倾斜，市场强烈看好
        - 指数接近 33: 资金分散，市场不确定
        - 必发指数与赔率背离时最值得关注 (如赔率看好但指数低)
    """
    total_volume = home_volume + draw_volume + away_volume

    if total_volume > 0:
        # 有真实成交量 → 直接用
        hi = home_volume / total_volume * 100
        di = draw_volume / total_volume * 100
        ai = away_volume / total_volume * 100
        source = "成交量"
    else:
        # 无成交量 → 用挂单量估算
        home_pending = home_back + home_lay
        draw_pending = draw_back + draw_lay
        away_pending = away_back + away_lay
        total_pending = home_pending + draw_pending + away_pending

        if total_pending > 0:
            hi = home_pending / total_pending * 100
            di = draw_pending / total_pending * 100
            ai = away_pending / total_pending * 100
            source = "挂单量估算"
        else:
            # 完全无数据 → 用赔率反推 (last resort)
            if home_back > 0 and draw_back > 0 and away_back > 0:
                implied = calculate_implied_probability(home_back, draw_back, away_back)
                hi = implied.home * 100
                di = implied.draw * 100
                ai = implied.away * 100
                source = "赔率反推"
            else:
                return BetfairIndex(home_index=0, draw_index=0, away_index=0,
                                    total_volume=0, source="无数据")

    return BetfairIndex(
        home_index=round(hi, 1),
        draw_index=round(di, 1),
        away_index=round(ai, 1),
        total_volume=round(total_volume, 2),
        source=source,
    )


# ============================================================
# 价值检测 (模型 vs 市场)
# ============================================================

def detect_value(
    model_home: float,
    model_draw: float,
    model_away: float,
    market_home: float,
    market_draw: float,
    market_away: float,
    kelly_multiplier: float = 0.25,  # 1/4 Kelly (保守)
) -> ValueDetection:
    """检测模型预测与市场赔率之间的价值

    Value = 模型概率 - 市场隐含概率

    解读:
        > +5%  → 显著价值，模型认为被低估
        > +2%  → 轻度价值
        < -5%  → 市场更看好，模型不认同
        -2%~+2% → 模型与市场一致

    凯利公式 (Kelly Criterion):
        f* = (b * p - q) / b
        其中 b = 赔率-1, p = 模型概率, q = 1-p

        1/4 Kelly = kelly_multiplier * f*
        用于保守投注，防止模型高估
    """
    hv = model_home - market_home
    dv = model_draw - market_draw
    av = model_away - market_away

    # 找出最有价值的方向
    values = {"主胜": hv, "平局": dv, "客胜": av}
    best_dir = max(values, key=values.get)
    best_val = values[best_dir]

    # 凯利计算
    kelly = 0.0
    if best_val > 0:
        # 需要赔率来计算凯利 (这里用隐含概率反推)
        if best_dir == "主胜" and market_home > 0:
            odds = 1.0 / market_home if market_home > 0 else 0
        elif best_dir == "平局" and market_draw > 0:
            odds = 1.0 / market_draw if market_draw > 0 else 0
        else:
            odds = 1.0 / market_away if market_away > 0 else 0

        if odds > 1.0:
            b = odds - 1.0
            p = max(values.values())
            q = 1.0 - p
            # Full Kelly
            f_star = (b * p - q) / b if b > 0 else 0
            kelly = max(0.0, f_star * kelly_multiplier)

    # 置信度
    if best_val > 0.05 and kelly > 0.03:
        confidence = "高"
    elif best_val > 0.02:
        confidence = "中"
    elif best_val > -0.02:
        confidence = "低"
    else:
        confidence = "无"

    return ValueDetection(
        home_value=round(hv, 4),
        draw_value=round(dv, 4),
        away_value=round(av, 4),
        best_value=best_dir if best_val > 0 else "none",
        kelly_fraction=round(kelly, 4),
        confidence=confidence,
    )


# ============================================================
# 综合分析
# ============================================================

def compare_odds_with_prediction(
    model_home: float,
    model_draw: float,
    model_away: float,
    odds_list: list[OddsLine],
    betfair_volumes: dict[str, float] | None = None,
) -> OddsComparison:
    """综合赔率对比分析

    输入:
        model_home/draw/away: 模型预测概率 (0~1)
        odds_list:            多家博彩公司赔率列表
        betfair_volumes:      必发成交量 (可选)

    返回:
        完整对比分析，包含:
        - 平均赔率 & 最佳赔率
        - 隐含概率 (margin 剥离后)
        - 必发指数
        - 价值检测
        - 推荐方向
    """
    if not odds_list:
        return OddsComparison(
            model_home=model_home, model_draw=model_draw, model_away=model_away,
        )

    # 平均赔率
    avg_home = sum(o.home for o in odds_list) / len(odds_list)
    avg_draw = sum(o.draw for o in odds_list) / len(odds_list)
    avg_away = sum(o.away for o in odds_list) / len(odds_list)

    avg_odds = OddsLine(
        bookmaker=f"市场平均 ({len(odds_list)}家)",
        home=round(avg_home, 2),
        draw=round(avg_draw, 2),
        away=round(avg_away, 2),
    )

    # 最佳赔率 (对投注者最有利)
    best_home = max(o.home for o in odds_list)
    best_draw = max(o.draw for o in odds_list)
    best_away = max(o.away for o in odds_list)

    best_bookmaker_home = next(o for o in odds_list if o.home == best_home)
    best_bookmaker_draw = next(o for o in odds_list if o.draw == best_draw)
    best_bookmaker_away = next(o for o in odds_list if o.away == best_away)

    best_odds = OddsLine(
        bookmaker=f"最佳组合 ({best_bookmaker_home.bookmaker}/{best_bookmaker_draw.bookmaker}/{best_bookmaker_away.bookmaker})",
        home=best_home,
        draw=best_draw,
        away=best_away,
    )

    # 隐含概率 (从平均赔率剥离 margin)
    implied = calculate_implied_probability(avg_home, avg_draw, avg_away)

    # 必发指数
    if betfair_volumes:
        bf_idx = calculate_betfair_index(**betfair_volumes)
    else:
        # 尝试从 odds_list 中找 Betfair 数据
        betfair_odds = [o for o in odds_list if "betfair" in o.bookmaker.lower()]
        if betfair_odds:
            bf = betfair_odds[0]
            bf_idx = calculate_betfair_index(
                home_back=bf.home, home_lay=0,
                draw_back=bf.draw, draw_lay=0,
                away_back=bf.away, away_lay=0,
            )
        else:
            # 用平均赔率反推
            bf_idx = calculate_betfair_index(
                home_back=avg_home, home_lay=0,
                draw_back=avg_draw, draw_lay=0,
                away_back=avg_away, away_lay=0,
            )
            bf_idx.source = "赔率反推 (非真实必发数据)"

    # 价值检测
    value = detect_value(
        model_home / 100 if model_home > 1 else model_home,
        model_draw / 100 if model_draw > 1 else model_draw,
        model_away / 100 if model_away > 1 else model_away,
        implied.home,
        implied.draw,
        implied.away,
    )

    return OddsComparison(
        home_team="",
        away_team="",
        avg_odds=avg_odds,
        best_odds=best_odds,
        bookmaker_count=len(odds_list),
        implied=implied,
        betfair_index=bf_idx,
        model_home=model_home,
        model_draw=model_draw,
        model_away=model_away,
        value=value,
        odds_table=odds_list,
    )
