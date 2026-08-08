"""
足球比赛预测模型

基于统计学方法:
1. 泊松分布模型 —— 预测比分概率
2. 攻防实力评估 —— 基于历史数据的进球期望
3. 近期状态加权 —— 最近 N 场比赛权重更高
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats


@dataclass
class TeamStats:
    """球队统计数据"""
    name: str = ""
    # 进攻指标
    avg_goals_scored: float = 1.5       # 场均进球
    avg_goals_conceded: float = 1.2     # 场均失球
    attack_strength: float = 1.0        # 攻击力 (相对联赛平均)
    defense_strength: float = 1.0        # 防守力 (相对联赛平均)
    # 近期状态
    recent_form: list[str] = field(default_factory=list)  # ['W','D','L',...]
    form_points: float = 0.0            # 近期场均积分
    # ELO
    elo_rating: float = 1500.0


@dataclass
class MatchPrediction:
    """单场比赛预测结果"""
    home_team: str = ""
    away_team: str = ""

    # 胜平负概率
    home_win_prob: float = 0.0
    draw_prob: float = 0.0
    away_win_prob: float = 0.0

    # 预期进球
    home_expected_goals: float = 0.0
    away_expected_goals: float = 0.0

    # 最可能比分
    likely_scores: list[tuple[tuple[int, int], float]] = field(default_factory=list)

    # 大小球
    over_25_prob: float = 0.0
    over_35_prob: float = 0.0

    # 双方进球
    both_to_score_prob: float = 0.0


class PoissonPredictor:
    """泊松分布比分预测器"""

    LEAGUE_AVG_HOME_GOALS = 1.53   # 联赛主场场均进球
    LEAGUE_AVG_AWAY_GOALS = 1.14   # 联赛客场场均进球

    def __init__(self) -> None:
        self.max_goals = 8  # 单队最大进球数 (概率截断)

    def predict(
        self,
        home_stats: TeamStats,
        away_stats: TeamStats,
        league_avg_home: float | None = None,
        league_avg_away: float | None = None,
    ) -> MatchPrediction:
        """预测比赛结果"""
        league_avg_home = league_avg_home or self.LEAGUE_AVG_HOME_GOALS
        league_avg_away = league_avg_away or self.LEAGUE_AVG_AWAY_GOALS

        # 1. 计算预期进球 (λ)
        home_lambda = (
            league_avg_home
            * home_stats.attack_strength
            * away_stats.defense_strength
        )
        away_lambda = (
            league_avg_away
            * away_stats.attack_strength
            * home_stats.defense_strength
        )

        home_lambda = max(home_lambda, 0.2)
        away_lambda = max(away_lambda, 0.2)

        # 2. 泊松概率矩阵
        home_probs = [self._poisson_pmf(i, home_lambda) for i in range(self.max_goals + 1)]
        away_probs = [self._poisson_pmf(j, away_lambda) for j in range(self.max_goals + 1)]

        # 3. 胜平负概率
        home_win = sum(
            home_probs[i] * away_probs[j]
            for i in range(self.max_goals + 1)
            for j in range(self.max_goals + 1)
            if i > j
        )
        draw = sum(
            home_probs[i] * away_probs[j]
            for i in range(self.max_goals + 1)
            for j in range(self.max_goals + 1)
            if i == j
        )
        away_win = sum(
            home_probs[i] * away_probs[j]
            for i in range(self.max_goals + 1)
            for j in range(self.max_goals + 1)
            if i < j
        )

        # 4. 最可能比分 Top 5
        score_probs: list[tuple[tuple[int, int], float]] = []
        for i in range(self.max_goals + 1):
            for j in range(self.max_goals + 1):
                prob = home_probs[i] * away_probs[j]
                score_probs.append(((i, j), prob))
        score_probs.sort(key=lambda x: x[1], reverse=True)

        # 5. 大小球概率
        over_25 = sum(
            prob for (i, j), prob in score_probs if i + j > 2.5
        )
        over_35 = sum(
            prob for (i, j), prob in score_probs if i + j > 3.5
        )

        # 6. 双方进球概率
        both_score = sum(
            prob for (i, j), prob in score_probs if i > 0 and j > 0
        )

        return MatchPrediction(
            home_team=home_stats.name,
            away_team=away_stats.name,
            home_win_prob=round(home_win, 4),
            draw_prob=round(draw, 4),
            away_win_prob=round(away_win, 4),
            home_expected_goals=round(home_lambda, 2),
            away_expected_goals=round(away_lambda, 2),
            likely_scores=score_probs[:5],
            over_25_prob=round(over_25, 4),
            over_35_prob=round(over_35, 4),
            both_to_score_prob=round(both_score, 4),
        )

    @staticmethod
    def _poisson_pmf(k: int, lam: float) -> float:
        """泊松概率质量函数"""
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    def estimate_strength(
        self,
        goals_scored: float,
        goals_conceded: float,
        league_avg_scored: float,
        league_avg_conceded: float,
    ) -> tuple[float, float]:
        """根据进球/失球数据估算攻防实力指数"""
        attack = goals_scored / league_avg_scored if league_avg_scored > 0 else 1.0
        defense = goals_conceded / league_avg_conceded if league_avg_conceded > 0 else 1.0
        return round(attack, 3), round(defense, 3)
