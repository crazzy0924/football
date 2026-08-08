"""
ELO 评分系统

用于评估球队实力及预测比赛结果
基于国际象棋 ELO 算法改编
"""
from __future__ import annotations

import math


class EloSystem:
    """足球 ELO 评分系统

    核心参数说明:
    - K (K-factor): 评分变化幅度, 足球常用 20-40
    - 主场优势: 加 100 分
    - 净胜球加成: 大胜获得更多 ELO 增长
    """

    DEFAULT_ELO = 1500.0
    K_FACTOR = 32.0               # 基础 K 值
    HOME_ADVANTAGE = 100.0        # 主场加分
    GOAL_DIFF_INDEX = 0.8         # 净胜球加成系数

    # 初始 ELO (基于 2024 实力)
    TEAM_INITIAL_ELO: dict[str, float] = {
        "Manchester City": 1880,
        "Arsenal": 1840,
        "Liverpool": 1820,
        "Chelsea": 1720,
        "Tottenham Hotspur": 1700,
        "Manchester United": 1700,
        "Newcastle United": 1680,
        "Aston Villa": 1670,
        "Brighton & Hove Albion": 1620,
        "West Ham United": 1600,
        "Crystal Palace": 1580,
        "Fulham": 1560,
        "Brentford": 1550,
        "Everton": 1540,
        "Wolverhampton Wanderers": 1530,
        "Nottingham Forest": 1510,
        "Bournemouth": 1500,
        "Leicester City": 1480,
        "Ipswich Town": 1440,
        "Southampton": 1430,
        "Real Madrid": 1900,
        "Barcelona": 1840,
        "Atlético Madrid": 1780,
        "Bayern München": 1860,
        "Borussia Dortmund": 1740,
        "Paris Saint-Germain": 1800,
        "Inter Milan": 1820,
        "AC Milan": 1760,
        "Juventus": 1760,
    }

    @classmethod
    def get_elo(cls, team_name: str) -> float:
        """获取球队 ELO，未知球队返回默认值"""
        return cls.TEAM_INITIAL_ELO.get(team_name, cls.DEFAULT_ELO)

    @classmethod
    def expected_result(cls, elo_a: float, elo_b: float, home: bool = False) -> float:
        """计算 A 队对 B 队的期望胜率 (0~1)

        Args:
            elo_a: A 队 ELO
            elo_b: B 队 ELO
            home: A 队是否主场
        """
        if home:
            elo_a += cls.HOME_ADVANTAGE
        return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))

    @classmethod
    def update(
        cls,
        elo_a: float,
        elo_b: float,
        goals_a: int,
        goals_b: int,
        home_a: bool = True,
    ) -> tuple[float, float]:
        """根据比赛结果更新 ELO

        Returns:
            (new_elo_a, new_elo_b)
        """
        expected_a = cls.expected_result(elo_a, elo_b, home_a)

        # 实际结果
        if goals_a > goals_b:
            actual_a = 1.0
        elif goals_a == goals_b:
            actual_a = 0.5
        else:
            actual_a = 0.0

        # 净胜球加成
        goal_diff = abs(goals_a - goals_b)
        if goal_diff <= 1:
            k_mult = 1.0
        elif goal_diff == 2:
            k_mult = 1.5
        else:
            k_mult = (11 + goal_diff) / 8  # 3球=1.75, 4球=1.875, 5球=2.0

        k = cls.K_FACTOR * k_mult

        delta = k * (actual_a - expected_a)
        new_elo_a = elo_a + delta
        new_elo_b = elo_b - delta

        return round(new_elo_a, 1), round(new_elo_b, 1)

    @classmethod
    def win_probability(
        cls, team_a: str, team_b: str, home_a: bool = True
    ) -> dict[str, float]:
        """根据 ELO 计算比赛胜平负概率

        Returns:
            {"home_win": ..., "draw": ..., "away_win": ...}
        """
        elo_a = cls.get_elo(team_a)
        elo_b = cls.get_elo(team_b)

        # 期望胜率
        exp_home = cls.expected_result(elo_a, elo_b, home_a)
        exp_away = 1.0 - exp_home

        # 平局概率 (经验公式: 差异越大, 平局概率越低)
        elo_diff = abs(elo_a - elo_b)
        draw_prob = 0.26 * math.exp(-elo_diff / 400.0)

        # 分配胜率
        home_win = exp_home - draw_prob * exp_home / (exp_home + exp_away) if (exp_home + exp_away) > 0 else exp_home
        away_win = exp_away - draw_prob * exp_away / (exp_home + exp_away) if (exp_home + exp_away) > 0 else exp_away

        # 确保非负
        home_win = max(home_win, 0.0)
        away_win = max(away_win, 0.0)
        total = home_win + draw_prob + away_win
        if total > 0:
            home_win /= total
            draw_prob /= total
            away_win /= total

        return {
            "home_win": round(home_win, 4),
            "draw": round(draw_prob, 4),
            "away_win": round(away_win, 4),
        }
