"""
回测引擎 —— 模型 vs 真实赛果 vs 市场赔率

核心指标:
  Brier Score   — 概率预测均方误差 (0~1, 越低越好, 0.25=随机猜测)
  Log Loss      — 对数损失 (越低越好, 惩罚"自信但错误"的预测)
  Accuracy      — 最高概率方向命中率
  Calibration   — 概率校准曲线 (预测 N% 的事件实际发生 N%?)
  Bias Matrix   — 系统性偏差检测 (主场高估? 平局低估?)

偏差调整:
  根据回测结果自动计算校准系数, 修正模型预测
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MatchResult:
    """一场比赛的完整回测记录"""
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    actual: str  # "H" | "D" | "A"

    # 模型预测概率
    model_home: float
    model_draw: float
    model_away: float

    # 模型预测的最可能结果
    model_pick: str = ""

    # 是否正确
    correct: bool = False

    # 预测 vs 实际偏差 (用于分析)
    brier_contribution: float = 0.0  # 该场的 Brier Score 贡献
    log_loss_contribution: float = 0.0  # 该场的 Log Loss 贡献

    # 市场赔率 (如有)
    market_home: float = 0.0
    market_draw: float = 0.0
    market_away: float = 0.0
    market_correct: bool = False

    # 比分预测
    predicted_score: str = ""
    expected_goals_home: float = 0.0
    expected_goals_away: float = 0.0


@dataclass
class BacktestReport:
    """回测报告"""
    date: str = ""
    total_matches: int = 0
    league: str = ""

    # ---- 核心指标 ----
    brier_score: float = 0.0        # 0~1, <0.20 优秀, 0.20-0.25 一般, >0.25 差
    log_loss: float = 0.0           # <0.9 优秀, 0.9-1.1 一般, >1.1 差
    accuracy: float = 0.0           # 命中率 (模型最高概率方向是否正确)
    market_accuracy: float = 0.0    # 市场赔率隐含的最高概率方向命中率 (对比基准)

    # ---- 偏差分析 ----
    home_overestimation: float = 0.0   # 正值 = 模型高估主胜概率
    draw_underestimation: float = 0.0  # 正值 = 模型低估平局概率
    away_overestimation: float = 0.0   # 正值 = 模型高估客胜概率

    # ---- 校准 ----
    calibration_home: list[dict] = field(default_factory=list)
    calibration_draw: list[dict] = field(default_factory=list)
    calibration_away: list[dict] = field(default_factory=list)
    calibration_quality: str = ""  # "良好" | "轻微失校准" | "严重失校准"

    # ---- 按联赛细分 ----
    by_league: dict[str, dict] = field(default_factory=dict)

    # ---- 调整建议 ----
    recommendations: list[str] = field(default_factory=list)
    adjustment_factors: dict[str, float] = field(default_factory=dict)

    # ---- 逐场明细 ----
    match_details: list[MatchResult] = field(default_factory=list)

    # ---- 模型 vs 市场对比 ----
    model_vs_market: dict[str, Any] = field(default_factory=dict)


# ============================================================
# 回测引擎
# ============================================================

class BacktestEngine:
    """足球预测回测引擎"""

    def __init__(self) -> None:
        pass

    async def review_yesterday(
        self,
        league_code: str = "PL",
        include_odds: bool = True,
    ) -> BacktestReport:
        """复盘昨日比赛

        流程:
        1. 获取昨日完赛数据 (比分)
        2. 对每场跑模型预测
        3. 对比真实结果
        4. (可选) 拉取 Kambi 赔率对比
        5. 计算偏差 & 生成调整建议
        """
        from src.data.kambi_client import KambiClient
        from src.agent.tools import predict_match

        kambi = KambiClient()
        matches = kambi.get_yesterday_matches(league_code)

        if not matches:
            # 无真实数据 → 使用模拟数据进行演示
            return self._demo_report(league_code)

        report = BacktestReport(
            date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            total_matches=len(matches),
            league=league_code,
        )

        details: list[MatchResult] = []
        total_brier = 0.0
        total_logloss = 0.0
        total_correct = 0
        total_market_correct = 0
        market_count = 0

        home_over_sum = 0.0
        draw_under_sum = 0.0
        away_over_sum = 0.0

        for m in matches:
            # 跑模型预测
            try:
                pred = await predict_match(
                    home_team=m["home_team"],
                    away_team=m["away_team"],
                )
            except Exception:
                continue

            # 解析预测
            model_h = pred["prediction"]["home_win"] / 100.0
            model_d = pred["prediction"]["draw"] / 100.0
            model_a = pred["prediction"]["away_win"] / 100.0

            # 实际结果向量
            actual_vec = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}[m["result"]]

            # Brier Score = (p_h - a_h)^2 + (p_d - a_d)^2 + (p_a - a_a)^2
            brier = (
                (model_h - actual_vec[0]) ** 2
                + (model_d - actual_vec[1]) ** 2
                + (model_a - actual_vec[2]) ** 2
            )

            # Log Loss = -ln(p_actual)
            actual_prob = {"H": model_h, "D": model_d, "A": model_a}[m["result"]]
            actual_prob = max(actual_prob, 1e-10)  # 防 log(0)
            logloss = -math.log(actual_prob)

            # 模型预测方向
            pick = max((model_h, "H"), (model_d, "D"), (model_a, "A"))[1]
            correct = (pick == m["result"])

            # 比分预测
            eg_h = pred["expected_goals"]["home"]
            eg_a = pred["expected_goals"]["away"]
            top_score = pred["likely_scores"][0]["score"] if pred["likely_scores"] else "?"

            mr = MatchResult(
                home_team=m["home_team"],
                away_team=m["away_team"],
                home_goals=m["home_goals"] or 0,
                away_goals=m["away_goals"] or 0,
                actual=m["result"],
                model_home=model_h,
                model_draw=model_d,
                model_away=model_a,
                model_pick=pick,
                correct=correct,
                brier_contribution=brier,
                log_loss_contribution=logloss,
                predicted_score=top_score,
                expected_goals_home=eg_h,
                expected_goals_away=eg_a,
            )

            # Kambi 赔率对比
            if include_odds and kambi.is_available:
                try:
                    odds_data = kambi.get_kambi_odds(m["fixture_id"])
                    kc = odds_data.get("kambi_implied")
                    if kc:
                        mr.market_home = kc["home"]
                        mr.market_draw = kc["draw"]
                        mr.market_away = kc["away"]
                        market_pick = max((kc["home"], "H"), (kc["draw"], "D"), (kc["away"], "A"))[1]
                        mr.market_correct = (market_pick == m["result"])
                        market_count += 1
                        if mr.market_correct:
                            total_market_correct += 1
                except Exception:
                    pass

            # 累计偏差
            if m["result"] == "H":
                home_over_sum += (model_h - 1.0)  # 预测太保守还是太激进
            elif m["result"] == "D":
                draw_under_sum += (1.0 - model_d)  # 对平局低估了多少
            elif m["result"] == "A":
                away_over_sum += (model_a - 1.0)

            details.append(mr)
            total_brier += brier
            total_logloss += logloss
            if correct:
                total_correct += 1

        n = len(details) or 1

        # 汇总
        report.brier_score = round(total_brier / n, 4)
        report.log_loss = round(total_logloss / n, 4)
        report.accuracy = round(total_correct / n, 4)
        report.market_accuracy = round(total_market_correct / market_count, 4) if market_count > 0 else 0.0

        report.home_overestimation = round(home_over_sum / n, 4)
        report.draw_underestimation = round(draw_under_sum / n, 4)
        report.away_overestimation = round(away_over_sum / n, 4)

        # 校准分析
        report.calibration_quality = self._assess_calibration(report)

        # 模型 vs 市场
        if market_count > 0:
            report.model_vs_market = {
                "model_accuracy": f"{report.accuracy * 100:.1f}%",
                "market_accuracy": f"{report.market_accuracy * 100:.1f}%",
                "model_vs_market_gap": f"{(report.accuracy - report.market_accuracy) * 100:+.1f}%",
                "verdict": (
                    "✅ 模型优于市场" if report.accuracy > report.market_accuracy + 0.03
                    else "⚠️ 模型落后市场" if report.market_accuracy > report.accuracy + 0.03
                    else "模型与市场持平"
                ),
            }

        # 调整建议
        report.recommendations = self._generate_recommendations(report)
        report.adjustment_factors = self._calc_adjustment_factors(report)
        report.match_details = details

        return report

    # ---- 校准评估 ----

    def _assess_calibration(self, report: BacktestReport) -> str:
        """评估概率校准质量"""
        issues = []

        if abs(report.home_overestimation) > 0.08:
            direction = "高估" if report.home_overestimation > 0 else "低估"
            issues.append(f"主胜概率系统性{direction} (偏差: {report.home_overestimation:+.1%})")

        if report.draw_underestimation > 0.05:
            issues.append(f"平局概率系统性命中不足 (低估: {report.draw_underestimation:+.1%})")

        if report.brier_score > 0.22:
            issues.append(f"Brier Score 偏高 ({report.brier_score:.3f})")

        if not issues:
            return "良好"
        elif len(issues) == 1:
            return "轻微失校准"
        else:
            return "严重失校准"

    # ---- 调整建议 ----

    def _generate_recommendations(self, report: BacktestReport) -> list[str]:
        """根据回测结果生成调整建议"""
        recs = []

        # Brier Score 解读
        if report.brier_score < 0.18:
            recs.append("✅ Brier Score 优秀 (<0.18): 概率预测整体准确")
        elif report.brier_score < 0.22:
            recs.append("Brier Score 可接受 (0.18-0.22): 有优化空间但方向正确")
        else:
            recs.append(f"⚠️ Brier Score 偏高 ({report.brier_score:.3f}): 建议调整模型权重")

        # Log Loss 解读
        if report.log_loss < 0.9:
            recs.append("✅ Log Loss 良好 (<0.9): 模型不会过度自信地犯错")
        elif report.log_loss < 1.1:
            recs.append('Log Loss 一般: 存在少数"自信但错误"的预测')
        else:
            recs.append(f"⚠️ Log Loss 偏高 ({report.log_loss:.3f}): 需降低极端概率预测")

        # 方向性偏差
        if report.home_overestimation > 0.05:
            recs.append(f"🔧 主胜概率高估 {report.home_overestimation:+.1%}: 建议降低泊松主场优势系数或 ELO 主场加成")
        elif report.home_overestimation < -0.05:
            recs.append(f"🔧 主胜概率低估 {report.home_overestimation:+.1%}: 建议提升主场优势权重")

        if report.draw_underestimation > 0.05:
            recs.append(f"🔧 平局概率低估 {report.draw_underestimation:+.1%}: 建议调整泊松模型中的平局区域 (draw expansion) 参数")
        elif report.draw_underestimation < -0.05:
            recs.append("平局概率高估: 考虑增加平局衰减因子")

        if report.away_overestimation > 0.05:
            recs.append(f"🔧 客胜概率高估 {report.away_overestimation:+.1%}: 建议提升客队客场衰减系数")
        elif report.away_overestimation < -0.05:
            recs.append(f"🔧 客胜概率低估 {report.away_overestimation:+.1%}: 建议降低客场惩罚")

        # 模型 vs 市场
        if report.model_vs_market:
            mvm = report.model_vs_market
            if "落后" in mvm.get("verdict", ""):
                recs.append(f"⚠️ 模型准确率落后市场 ({mvm.get('model_vs_market_gap', '')}): 建议在预测中加入赔率信息作为先验")
            elif "优于" in mvm.get("verdict", ""):
                recs.append(f"✅ 模型准确率优于市场 ({mvm.get('model_vs_market_gap', '')}): 当前模型方向正确")

        if not recs:
            recs.append("数据不足, 继续收集更多比赛后进行回测")

        return recs

    # ---- 调整因子 ----

    def _calc_adjustment_factors(self, report: BacktestReport) -> dict[str, float]:
        """计算模型校准系数

        基于贝叶斯平滑: 将偏差量转化为权重修正

        Returns:
            {
                "home_advantage_adj": 0.92,  # 主场优势系数调整为原来的 92%
                "draw_expansion": 1.15,      # 平局概率扩展 15%
                "elo_away_penalty": 1.08,    # 客场 ELO 惩罚强化 8%
            }
        """
        factors = {}

        # 主场优势调整 (基于 home_overestimation)
        if abs(report.home_overestimation) > 0.02:
            # 主场高估 → 降低主场优势系数
            base_ha = 100  # ELO 主场加成默认 100
            adj_ha = base_ha * (1.0 - report.home_overestimation * 2)
            factors["elo_home_advantage"] = round(max(40, min(160, adj_ha)), 0)

        # 平局扩展 (基于 draw_underestimation)
        if report.draw_underestimation > 0.02:
            # 平局被低估 → 扩展泊松平局区域
            factors["draw_expansion"] = round(1.0 + report.draw_underestimation * 3, 2)

        # 模型融合权重调整
        if report.accuracy < 0.50 and report.market_accuracy > report.accuracy:
            # 模型不如市场 → 增加市场信息权重
            factors["poisson_weight"] = 0.45  # 从 0.60 降低
            factors["elo_weight"] = 0.25      # 从 0.40 降低
            factors["market_weight"] = 0.30   # 新加入市场先验

        return factors

    # ---- 模拟复盘 (无API时) ----

    def _demo_report(self, league_code: str) -> BacktestReport:
        """生成演示回测报告 (无真实 API 时使用)"""
        import random
        rng = random.Random(42)

        teams = [
            ("Arsenal", "Chelsea"), ("Manchester City", "Liverpool"),
            ("Tottenham", "Newcastle"), ("Manchester United", "Aston Villa"),
            ("Brighton", "West Ham"), ("Fulham", "Everton"),
            ("Crystal Palace", "Brentford"), ("Wolves", "Nottingham Forest"),
        ]

        details = []
        correct_count = 0
        for home, away in teams:
            hg = rng.randint(0, 4)
            ag = rng.randint(0, 3)
            actual = "H" if hg > ag else "A" if ag > hg else "D"

            model_h = 0.35 + rng.random() * 0.30
            model_d = 0.20 + rng.random() * 0.15
            model_a = 1.0 - model_h - model_d
            if model_a < 0.1:
                model_a = 0.1
                model_h = 1.0 - model_d - model_a

            pick = max((model_h, "H"), (model_d, "D"), (model_a, "A"))[1]
            correct = (pick == actual)
            if correct:
                correct_count += 1

            details.append(MatchResult(
                home_team=home, away_team=away,
                home_goals=hg, away_goals=ag,
                actual=actual,
                model_home=model_h, model_draw=model_d, model_away=model_a,
                model_pick=pick, correct=correct,
            ))

        n = len(details)
        brier = sum(
            (m.model_home - {"H": 1, "D": 0, "A": 0}[m.actual]) ** 2
            + (m.model_draw - {"H": 0, "D": 1, "A": 0}[m.actual]) ** 2
            + (m.model_away - {"H": 0, "D": 0, "A": 1}[m.actual]) ** 2
            for m in details
        ) / n

        report = BacktestReport(
            date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            total_matches=n, league=league_code,
            brier_score=round(brier, 4),
            accuracy=round(correct_count / n, 4),
            match_details=details,
        )
        report.recommendations = self._generate_recommendations(report)
        report.note = "⚠️ 演示数据 —— 配置 API-Football 可回测真实比赛"
        return report


# ============================================================
# 便捷函数
# ============================================================

async def review_and_adjust(league_code: str = "PL") -> dict[str, Any]:
    """复盘昨日比赛 + 输出调整建议 (一步到位)"""
    engine = BacktestEngine()
    report = await engine.review_yesterday(league_code, include_odds=True)

    return {
        "date": report.date,
        "matches_reviewed": report.total_matches,
        "league": report.league,
        "metrics": {
            "brier_score": report.brier_score,
            "log_loss": report.log_loss,
            "accuracy": f"{report.accuracy * 100:.1f}%",
            "calibration": report.calibration_quality,
        },
        "biases": {
            "home_overestimation": f"{report.home_overestimation:+.1%}",
            "draw_underestimation": f"{report.draw_underestimation:+.1%}",
            "away_overestimation": f"{report.away_overestimation:+.1%}",
        },
        "model_vs_market": report.model_vs_market,
        "recommendations": report.recommendations,
        "adjustment_factors": report.adjustment_factors,
        "match_details": [
            {
                "match": f"{m.home_team} {m.home_goals}-{m.away_goals} {m.away_team}",
                "actual": {"H": "主胜", "D": "平局", "A": "客胜"}[m.actual],
                "model_predicted": m.model_pick,
                "correct": "✅" if m.correct else "❌",
                "model_probs": f"主{m.model_home:.0%}/平{m.model_draw:.0%}/客{m.model_away:.0%}",
                "expected_score": m.predicted_score,
            }
            for m in report.match_details
        ],
    }
