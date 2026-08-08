"""
联赛自适应引擎

核心洞察 (8月4日复盘):
  统一模板套所有联赛 → 致命缺陷
  欧战资格赛主场胜率仅40%，联赛55%+
  不同联赛的进球率、平局率、角球率差异巨大

解决方案:
  为每个联赛维护独立画像(profile)
  预测时自动匹配联赛参数
  支持联赛间差异的量化对比
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 联赛画像数据结构
# ============================================================

@dataclass
class LeagueProfile:
    """联赛统计画像"""
    name: str                          # 联赛名
    code: str                          # 代码 (PL/PD/BL1/...)
    region: str = "europe"            # europe / americas / asia

    # ---- 进球特征 ----
    avg_home_goals: float = 1.50      # 主队场均进球
    avg_away_goals: float = 1.15      # 客队场均进球
    avg_total_goals: float = 2.65     # 场均总进球

    # ---- 胜平负分布 ----
    home_win_rate: float = 0.45       # 主胜率
    draw_rate: float = 0.25           # 平局率
    away_win_rate: float = 0.30       # 客胜率

    # ---- 主场优势 ----
    home_advantage_elo: float = 100   # ELO主场加分
    home_goal_boost: float = 0.30     # 主场进球加成因子

    # ---- 市场特征 ----
    over_25_rate: float = 0.50        # 大2.5球率
    btts_rate: float = 0.52           # 双方进球率
    avg_corners: float = 9.8          # 场均角球
    corner_home_share: float = 0.55   # 主队角球占比

    # ---- ELO校准 ----
    elo_base: float = 1500            # 联赛基准ELO
    elo_spread: float = 200           # 联赛内部ELO离散度

    # ---- 风格标签 ----
    style: str = ""                   # high_scoring / defensive / physical / technical
    notes: str = ""

    # ---- 多赛季验证数据 (用于置信区间) ----
    multi_season: list[dict] = field(default_factory=list)
    # [{"season":"23-24","home_win":0.46,"draw":0.22,"away_win":0.32,"goals":3.28,"over25":0.56,"btts":0.54}, ...]

    @property
    def season_count(self) -> int:
        return len(self.multi_season)

    @property
    def home_win_std(self) -> float:
        if len(self.multi_season) < 2: return 0.03
        vals = [s["home_win"] for s in self.multi_season]
        mean = sum(vals)/len(vals)
        return (sum((v-mean)**2 for v in vals)/(len(vals)-1))**0.5


# ============================================================
# 全球联赛画像数据库
# ============================================================

LEAGUE_PROFILES: dict[str, LeagueProfile] = {
    # ---- 欧洲五大联赛 ----
    "PL": LeagueProfile(
        name="英超", code="PL", region="europe",
        avg_home_goals=1.62, avg_away_goals=1.22, avg_total_goals=2.84,
        home_win_rate=0.44, draw_rate=0.23, away_win_rate=0.33,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.55, btts_rate=0.54, avg_corners=10.3, corner_home_share=0.56,
        elo_base=1600, elo_spread=250,
        style="high_intensity", notes="节奏最快, 身体对抗强, 主场优势适中",
        multi_season=[
            {"season":"20-21","home_win":0.38,"draw":0.22,"away_win":0.40,"goals":2.69,"over25":0.49,"btts":0.50},
            {"season":"21-22","home_win":0.43,"draw":0.23,"away_win":0.34,"goals":2.82,"over25":0.52,"btts":0.52},
            {"season":"22-23","home_win":0.45,"draw":0.24,"away_win":0.31,"goals":2.85,"over25":0.53,"btts":0.53},
            {"season":"23-24","home_win":0.46,"draw":0.22,"away_win":0.32,"goals":3.28,"over25":0.58,"btts":0.56},
            {"season":"24-25","home_win":0.44,"draw":0.25,"away_win":0.31,"goals":2.92,"over25":0.54,"btts":0.53},
        ],
    ),
    "PD": LeagueProfile(
        name="西甲", code="PD", region="europe",
        avg_home_goals=1.45, avg_away_goals=1.05, avg_total_goals=2.50,
        home_win_rate=0.47, draw_rate=0.25, away_win_rate=0.28,
        home_advantage_elo=100, home_goal_boost=0.35,
        over_25_rate=0.48, btts_rate=0.48, avg_corners=9.2, corner_home_share=0.54,
        elo_base=1580, elo_spread=280,
        style="technical", notes="控球为主, 技术流, 比分偏低"
    ),
    "BL1": LeagueProfile(
        name="德甲", code="BL1", region="europe",
        avg_home_goals=1.70, avg_away_goals=1.30, avg_total_goals=3.00,
        home_win_rate=0.44, draw_rate=0.22, away_win_rate=0.34,
        home_advantage_elo=85, home_goal_boost=0.25,
        over_25_rate=0.58, btts_rate=0.56, avg_corners=10.0, corner_home_share=0.54,
        elo_base=1560, elo_spread=220,
        style="high_scoring", notes="进球最多的五大联赛, 高位逼抢盛行, 大球率高"
    ),
    "SA": LeagueProfile(
        name="意甲", code="SA", region="europe",
        avg_home_goals=1.42, avg_away_goals=1.02, avg_total_goals=2.44,
        home_win_rate=0.42, draw_rate=0.28, away_win_rate=0.30,
        home_advantage_elo=95, home_goal_boost=0.30,
        over_25_rate=0.46, btts_rate=0.47, avg_corners=9.5, corner_home_share=0.54,
        elo_base=1550, elo_spread=200,
        style="defensive", notes="防守为先, 平局率最高(28%), 小球率高",
        multi_season=[
            {"season":"20-21","home_win":0.40,"draw":0.27,"away_win":0.33,"goals":2.74,"over25":0.52,"btts":0.52},
            {"season":"21-22","home_win":0.41,"draw":0.29,"away_win":0.30,"goals":2.58,"over25":0.47,"btts":0.48},
            {"season":"22-23","home_win":0.43,"draw":0.26,"away_win":0.31,"goals":2.48,"over25":0.44,"btts":0.46},
            {"season":"23-24","home_win":0.42,"draw":0.28,"away_win":0.30,"goals":2.40,"over25":0.44,"btts":0.46},
            {"season":"24-25","home_win":0.42,"draw":0.28,"away_win":0.30,"goals":2.50,"over25":0.46,"btts":0.48},
        ],
    ),
    "BL1": LeagueProfile(
        name="德甲", code="BL1", region="europe",
        avg_home_goals=1.72, avg_away_goals=1.32, avg_total_goals=3.04,
        home_win_rate=0.44, draw_rate=0.22, away_win_rate=0.34,
        home_advantage_elo=85, home_goal_boost=0.25,
        over_25_rate=0.58, btts_rate=0.56, avg_corners=10.0, corner_home_share=0.54,
        elo_base=1560, elo_spread=220,
        style="high_scoring", notes="进球最多五大联赛, 高位逼抢盛行, 大球率最高",
        multi_season=[
            {"season":"20-21","home_win":0.40,"draw":0.24,"away_win":0.36,"goals":2.94,"over25":0.55,"btts":0.54},
            {"season":"21-22","home_win":0.43,"draw":0.23,"away_win":0.34,"goals":2.98,"over25":0.56,"btts":0.55},
            {"season":"22-23","home_win":0.44,"draw":0.22,"away_win":0.34,"goals":3.12,"over25":0.59,"btts":0.57},
            {"season":"23-24","home_win":0.45,"draw":0.21,"away_win":0.34,"goals":3.18,"over25":0.60,"btts":0.58},
            {"season":"24-25","home_win":0.44,"draw":0.22,"away_win":0.34,"goals":3.05,"over25":0.58,"btts":0.56},
        ],
    ),
    "PD": LeagueProfile(
        name="西甲", code="PD", region="europe",
        avg_home_goals=1.48, avg_away_goals=1.05, avg_total_goals=2.53,
        home_win_rate=0.47, draw_rate=0.25, away_win_rate=0.28,
        home_advantage_elo=100, home_goal_boost=0.35,
        over_25_rate=0.49, btts_rate=0.49, avg_corners=9.3, corner_home_share=0.54,
        elo_base=1580, elo_spread=280,
        style="technical", notes="控球为主, 技术流, 比分偏低, 主场优势强(47%)",
        multi_season=[
            {"season":"20-21","home_win":0.49,"draw":0.24,"away_win":0.27,"goals":2.48,"over25":0.46,"btts":0.47},
            {"season":"21-22","home_win":0.46,"draw":0.26,"away_win":0.28,"goals":2.50,"over25":0.48,"btts":0.48},
            {"season":"22-23","home_win":0.47,"draw":0.25,"away_win":0.28,"goals":2.55,"over25":0.49,"btts":0.49},
            {"season":"23-24","home_win":0.47,"draw":0.26,"away_win":0.27,"goals":2.52,"over25":0.49,"btts":0.49},
            {"season":"24-25","home_win":0.46,"draw":0.25,"away_win":0.29,"goals":2.58,"over25":0.50,"btts":0.50},
        ],
    ),
    "FL1": LeagueProfile(
        name="法甲", code="FL1", region="europe",
        avg_home_goals=1.52, avg_away_goals=1.18, avg_total_goals=2.70,
        home_win_rate=0.43, draw_rate=0.27, away_win_rate=0.30,
        home_advantage_elo=95, home_goal_boost=0.30,
        over_25_rate=0.51, btts_rate=0.51, avg_corners=9.0, corner_home_share=0.53,
        elo_base=1520, elo_spread=250,
        style="physical", notes="身体对抗强, PSG拉高均值, 中小球队偏防守",
        multi_season=[
            {"season":"20-21","home_win":0.42,"draw":0.27,"away_win":0.31,"goals":2.72,"over25":0.52,"btts":0.51},
            {"season":"21-22","home_win":0.43,"draw":0.26,"away_win":0.31,"goals":2.68,"over25":0.50,"btts":0.50},
            {"season":"22-23","home_win":0.429,"draw":0.242,"away_win":0.329,"goals":2.81,"over25":0.53,"btts":0.52},
            {"season":"23-24","home_win":0.42,"draw":0.29,"away_win":0.29,"goals":2.70,"over25":0.50,"btts":0.50},
        ],
    ),

    # ---- 欧洲二级联赛 ----
    "ELC": LeagueProfile(
        name="英冠", code="ELC", region="europe",
        avg_home_goals=1.42, avg_away_goals=1.08, avg_total_goals=2.50,
        home_win_rate=0.45, draw_rate=0.23, away_win_rate=0.32,
        home_advantage_elo=85, home_goal_boost=0.27,
        over_25_rate=0.49, btts_rate=0.48, avg_corners=10.0, corner_home_share=0.55,
        elo_base=1420, elo_spread=180,
        style="physical", notes="赛程密集, 体能消耗大. 主胜45%/平23%, 最常比分1-0(19%)",
        multi_season=[
            {"season":"23-24","home_win":0.446,"draw":0.234,"away_win":0.321,"goals":2.68,"over25":0.49,"btts":0.48},
        ],
    ),
    "DED": LeagueProfile(
        name="荷甲", code="DED", region="europe",
        avg_home_goals=1.80, avg_away_goals=1.35, avg_total_goals=3.15,
        home_win_rate=0.43, draw_rate=0.25, away_win_rate=0.32,
        home_advantage_elo=80, home_goal_boost=0.22,
        over_25_rate=0.65, btts_rate=0.60, avg_corners=10.7, corner_home_share=0.55,
        elo_base=1480, elo_spread=200,
        style="high_scoring", notes="进球狂魔联赛(3.24球/场)! 防守松散, 大2.5率65%全欧最高",
        multi_season=[
            {"season":"23-24","home_win":0.427,"draw":0.249,"away_win":0.324,"goals":3.24,"over25":0.654,"btts":0.60},
        ],
    ),
    "PPL": LeagueProfile(
        name="葡超", code="PPL", region="europe",
        avg_home_goals=1.50, avg_away_goals=1.05, avg_total_goals=2.55,
        home_win_rate=0.46, draw_rate=0.25, away_win_rate=0.29,
        home_advantage_elo=110, home_goal_boost=0.38,
        over_25_rate=0.50, btts_rate=0.49, avg_corners=9.5, corner_home_share=0.56,
        elo_base=1500, elo_spread=300,
        style="technical", notes="三强垄断, 主场优势强, ELO离散度大"
    ),

    # ---- 欧战 ----
    "CL": LeagueProfile(
        name="欧冠", code="CL", region="europe",
        avg_home_goals=1.55, avg_away_goals=1.15, avg_total_goals=2.70,
        home_win_rate=0.46, draw_rate=0.24, away_win_rate=0.30,
        home_advantage_elo=80, home_goal_boost=0.25,
        over_25_rate=0.53, btts_rate=0.52, avg_corners=9.5, corner_home_share=0.54,
        elo_base=1650, elo_spread=350,
        style="elite", notes="小组赛/淘汰赛主场强, 资格赛主场弱(40%)"
    ),
    "CLQ": LeagueProfile(  # 欧冠资格赛
        name="欧冠资格赛", code="CLQ", region="europe",
        avg_home_goals=1.35, avg_away_goals=1.15, avg_total_goals=2.50,
        home_win_rate=0.40, draw_rate=0.28, away_win_rate=0.32,
        home_advantage_elo=60, home_goal_boost=0.18,
        over_25_rate=0.48, btts_rate=0.47, avg_corners=9.2, corner_home_share=0.52,
        elo_base=1500, elo_spread=400,
        style="knockout", notes="⚠ 关键: 主场胜率仅40%! 主客场差距最小的赛事之一。中立场地频繁。",
        multi_season=[
            {"season":"21-22","home_win":0.42,"draw":0.25,"away_win":0.33,"goals":2.55,"over25":0.50,"btts":0.49},
            {"season":"22-23","home_win":0.38,"draw":0.30,"away_win":0.32,"goals":2.42,"over25":0.46,"btts":0.46},
            {"season":"23-24","home_win":0.41,"draw":0.27,"away_win":0.32,"goals":2.48,"over25":0.47,"btts":0.47},
            {"season":"24-25","home_win":0.40,"draw":0.28,"away_win":0.32,"goals":2.52,"over25":0.48,"btts":0.47},
            {"season":"25-26","home_win":0.40,"draw":0.28,"away_win":0.32,"goals":2.50,"over25":0.48,"btts":0.47},
        ],
    ),
    "MLS": LeagueProfile(
        name="美职联", code="MLS", region="americas",
        avg_home_goals=1.72, avg_away_goals=1.25, avg_total_goals=2.97,
        home_win_rate=0.48, draw_rate=0.23, away_win_rate=0.29,
        home_advantage_elo=120, home_goal_boost=0.38,
        over_25_rate=0.58, btts_rate=0.56, avg_corners=9.8, corner_home_share=0.57,
        elo_base=1480, elo_spread=180,
        style="high_scoring", notes="⚠ MLS主场优势强(48%), 长途旅行削弱客队. 24赛季进球3.11球创新高",
        multi_season=[
            {"season":"21","home_win":0.52,"draw":0.20,"away_win":0.28,"goals":2.82,"over25":0.55,"btts":0.54},
            {"season":"22","home_win":0.49,"draw":0.23,"away_win":0.28,"goals":2.88,"over25":0.56,"btts":0.55},
            {"season":"23","home_win":0.51,"draw":0.21,"away_win":0.28,"goals":2.85,"over25":0.55,"btts":0.54},
            {"season":"24","home_win":0.45,"draw":0.25,"away_win":0.30,"goals":3.11,"over25":0.58,"btts":0.56},
        ],
    ),
    "EL": LeagueProfile(
        name="欧联", code="EL", region="europe",
        avg_home_goals=1.45, avg_away_goals=1.10, avg_total_goals=2.55,
        home_win_rate=0.44, draw_rate=0.26, away_win_rate=0.30,
        home_advantage_elo=75, home_goal_boost=0.22,
        over_25_rate=0.50, btts_rate=0.50, avg_corners=9.2, corner_home_share=0.53,
        elo_base=1550, elo_spread=350,
        style="mixed", notes="欧冠资格赛和正赛之间, 球队实力差异大"
    ),

    # ---- 美洲 ----
    "LIGA_MX": LeagueProfile(
        name="墨超", code="LIGA_MX", region="americas",
        avg_home_goals=1.55, avg_away_goals=1.20, avg_total_goals=2.75,
        home_win_rate=0.45, draw_rate=0.27, away_win_rate=0.28,
        home_advantage_elo=115, home_goal_boost=0.34,
        over_25_rate=0.53, btts_rate=0.52, avg_corners=9.5, corner_home_share=0.56,
        elo_base=1500, elo_spread=200,
        style="physical", notes="高海拔主场独特优势. 总球2.75, 季后赛赛制. 多赛季均值2.90球",
        multi_season=[
            {"season":"23-24","home_win":0.46,"draw":0.26,"away_win":0.28,"goals":2.88,"over25":0.54,"btts":0.53},
            {"season":"24-25","home_win":0.45,"draw":0.28,"away_win":0.27,"goals":2.86,"over25":0.53,"btts":0.52},
        ],
    ),
    "BSA": LeagueProfile(
        name="巴甲", code="BSA", region="americas",
        avg_home_goals=1.40, avg_away_goals=1.02, avg_total_goals=2.42,
        home_win_rate=0.47, draw_rate=0.26, away_win_rate=0.27,
        home_advantage_elo=105, home_goal_boost=0.33,
        over_25_rate=0.44, btts_rate=0.45, avg_corners=10.0, corner_home_share=0.55,
        elo_base=1500, elo_spread=220,
        style="physical", notes="南美主场氛围强(47%胜率). 低比分联赛(2.44球), 小球倾向",
        multi_season=[
            {"season":"2023","home_win":0.468,"draw":0.258,"away_win":0.274,"goals":2.49,"over25":0.45,"btts":0.46},
            {"season":"2024","home_win":0.47,"draw":0.27,"away_win":0.26,"goals":2.44,"over25":0.44,"btts":0.45},
        ],
    ),
    "LC": LeagueProfile(  # Leagues Cup (MLS vs 墨超)
        name="北美联杯", code="LC", region="americas",
        avg_home_goals=1.60, avg_away_goals=1.20, avg_total_goals=2.80,
        home_win_rate=0.48, draw_rate=0.24, away_win_rate=0.28,
        home_advantage_elo=120, home_goal_boost=0.35,
        over_25_rate=0.55, btts_rate=0.53, avg_corners=9.8, corner_home_share=0.56,
        elo_base=1500, elo_spread=250,
        style="mixed", notes="MLS主场有额外旅行优势, 墨超客场大幅削弱"
    ),

    # ── 其他欧洲联赛 ──
    "BL2": LeagueProfile(
        name="德乙", code="BL2", region="europe",
        avg_home_goals=1.55, avg_away_goals=1.20, avg_total_goals=2.75,
        home_win_rate=0.43, draw_rate=0.26, away_win_rate=0.31,
        home_advantage_elo=80, home_goal_boost=0.25,
        over_25_rate=0.53, btts_rate=0.52, avg_corners=9.8, corner_home_share=0.54,
        elo_base=1420, elo_spread=180,
        style="physical", notes="德乙进球偏多, 竞争激烈"
    ),
    "SCO": LeagueProfile(
        name="苏超", code="SCO", region="europe",
        avg_home_goals=1.50, avg_away_goals=1.10, avg_total_goals=2.60,
        home_win_rate=0.42, draw_rate=0.24, away_win_rate=0.34,
        home_advantage_elo=85, home_goal_boost=0.28,
        over_25_rate=0.50, btts_rate=0.50, avg_corners=10.2, corner_home_share=0.55,
        elo_base=1380, elo_spread=350,
        style="physical", notes="Old Firm垄断, ELO离散度大"
    ),
    "AUT": LeagueProfile(
        name="奥甲", code="AUT", region="europe",
        avg_home_goals=1.52, avg_away_goals=1.18, avg_total_goals=2.70,
        home_win_rate=0.43, draw_rate=0.24, away_win_rate=0.33,
        home_advantage_elo=85, home_goal_boost=0.26,
        over_25_rate=0.52, btts_rate=0.51, avg_corners=9.5, corner_home_share=0.54,
        elo_base=1400, elo_spread=220,
        style="mixed", notes="萨尔茨堡红牛垄断"
    ),
    "BEL": LeagueProfile(
        name="比甲", code="BEL", region="europe",
        avg_home_goals=1.55, avg_away_goals=1.20, avg_total_goals=2.75,
        home_win_rate=0.44, draw_rate=0.24, away_win_rate=0.32,
        home_advantage_elo=85, home_goal_boost=0.26,
        over_25_rate=0.53, btts_rate=0.53, avg_corners=9.6, corner_home_share=0.54,
        elo_base=1420, elo_spread=200,
        style="mixed", notes="季后赛赛制特殊"
    ),
    "DEN": LeagueProfile(
        name="丹超", code="DEN", region="europe",
        avg_home_goals=1.50, avg_away_goals=1.15, avg_total_goals=2.65,
        home_win_rate=0.43, draw_rate=0.25, away_win_rate=0.32,
        home_advantage_elo=85, home_goal_boost=0.26,
        over_25_rate=0.51, btts_rate=0.50, avg_corners=9.3, corner_home_share=0.54,
        elo_base=1400, elo_spread=180,
        style="mixed", notes="北欧联赛, 赛季与主流错位"
    ),
    "NOR": LeagueProfile(
        name="挪超", code="NOR", region="europe",
        avg_home_goals=1.60, avg_away_goals=1.20, avg_total_goals=2.80,
        home_win_rate=0.44, draw_rate=0.23, away_win_rate=0.33,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.55, btts_rate=0.54, avg_corners=9.8, corner_home_share=0.55,
        elo_base=1380, elo_spread=160,
        style="high_scoring", notes="北欧进球偏多, 人工草皮主场优势"
    ),
    "SWE": LeagueProfile(
        name="瑞典超", code="SWE", region="europe",
        avg_home_goals=1.48, avg_away_goals=1.12, avg_total_goals=2.60,
        home_win_rate=0.43, draw_rate=0.24, away_win_rate=0.33,
        home_advantage_elo=85, home_goal_boost=0.26,
        over_25_rate=0.50, btts_rate=0.50, avg_corners=9.5, corner_home_share=0.54,
        elo_base=1360, elo_spread=150,
        style="mixed", notes="马尔默统治"
    ),
    "POL": LeagueProfile(
        name="波甲", code="POL", region="europe",
        avg_home_goals=1.42, avg_away_goals=1.08, avg_total_goals=2.50,
        home_win_rate=0.45, draw_rate=0.25, away_win_rate=0.30,
        home_advantage_elo=90, home_goal_boost=0.30,
        over_25_rate=0.48, btts_rate=0.47, avg_corners=9.5, corner_home_share=0.55,
        elo_base=1380, elo_spread=180,
        style="defensive", notes="⚠ 波兰联赛小球, 大球慎推"
    ),
    "CZE": LeagueProfile(
        name="捷甲", code="CZE", region="europe",
        avg_home_goals=1.45, avg_away_goals=1.10, avg_total_goals=2.55,
        home_win_rate=0.44, draw_rate=0.26, away_win_rate=0.30,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.49, btts_rate=0.48, avg_corners=9.8, corner_home_share=0.55,
        elo_base=1380, elo_spread=200,
        style="defensive", notes="⚠ 捷克联赛小球倾向, 大球慎推"
    ),
    "SWI": LeagueProfile(
        name="瑞士超", code="SWI", region="europe",
        avg_home_goals=1.55, avg_away_goals=1.20, avg_total_goals=2.75,
        home_win_rate=0.44, draw_rate=0.24, away_win_rate=0.32,
        home_advantage_elo=85, home_goal_boost=0.25,
        over_25_rate=0.53, btts_rate=0.52, avg_corners=9.5, corner_home_share=0.54,
        elo_base=1400, elo_spread=220,
        style="mixed", notes="年轻人/巴塞尔主导"
    ),
    "ROM": LeagueProfile(
        name="罗甲", code="ROM", region="europe",
        avg_home_goals=1.35, avg_away_goals=1.05, avg_total_goals=2.40,
        home_win_rate=0.43, draw_rate=0.27, away_win_rate=0.30,
        home_advantage_elo=90, home_goal_boost=0.30,
        over_25_rate=0.45, btts_rate=0.45, avg_corners=9.2, corner_home_share=0.55,
        elo_base=1350, elo_spread=200,
        style="defensive", notes="东欧小球联赛"
    ),
    "BUL": LeagueProfile(
        name="保甲", code="BUL", region="europe",
        avg_home_goals=1.35, avg_away_goals=1.00, avg_total_goals=2.35,
        home_win_rate=0.44, draw_rate=0.27, away_win_rate=0.29,
        home_advantage_elo=95, home_goal_boost=0.32,
        over_25_rate=0.44, btts_rate=0.44, avg_corners=9.0, corner_home_share=0.55,
        elo_base=1320, elo_spread=200,
        style="defensive", notes="东欧小球联赛"
    ),
    "HUN": LeagueProfile(
        name="匈甲", code="HUN", region="europe",
        avg_home_goals=1.45, avg_away_goals=1.10, avg_total_goals=2.55,
        home_win_rate=0.44, draw_rate=0.25, away_win_rate=0.31,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.50, btts_rate=0.49, avg_corners=9.3, corner_home_share=0.55,
        elo_base=1350, elo_spread=200,
        style="mixed", notes="费伦茨瓦罗斯主导"
    ),

    # ── 亚洲 ──
    "J1": LeagueProfile(
        name="J联赛", code="J1", region="asia",
        avg_home_goals=1.40, avg_away_goals=1.10, avg_total_goals=2.50,
        home_win_rate=0.40, draw_rate=0.25, away_win_rate=0.35,
        home_advantage_elo=70, home_goal_boost=0.20,
        over_25_rate=0.48, btts_rate=0.47, avg_corners=9.0, corner_home_share=0.52,
        elo_base=1400, elo_spread=120,
        style="technical", notes="J联赛主场优势弱(40%), 客胜率高, 平局多"
    ),
    "CSL": LeagueProfile(
        name="中超", code="CSL", region="asia",
        avg_home_goals=1.55, avg_away_goals=1.15, avg_total_goals=2.70,
        home_win_rate=0.44, draw_rate=0.25, away_win_rate=0.31,
        home_advantage_elo=90, home_goal_boost=0.28,
        over_25_rate=0.52, btts_rate=0.50, avg_corners=9.2, corner_home_share=0.54,
        elo_base=1350, elo_spread=200,
        style="mixed", notes="外援依赖度高, 主场优势适中"
    ),
    "KLEAGUE": LeagueProfile(
        name="K联赛", code="KLEAGUE", region="asia",
        avg_home_goals=1.40, avg_away_goals=1.05, avg_total_goals=2.45,
        home_win_rate=0.42, draw_rate=0.27, away_win_rate=0.31,
        home_advantage_elo=85, home_goal_boost=0.26,
        over_25_rate=0.46, btts_rate=0.46, avg_corners=8.8, corner_home_share=0.53,
        elo_base=1380, elo_spread=150,
        style="defensive", notes="K联赛小球倾向, 防守为先"
    ),
    "J2": LeagueProfile(
        name="日乙", code="J2", region="asia",
        avg_home_goals=1.30, avg_away_goals=1.05, avg_total_goals=2.35,
        home_win_rate=0.39, draw_rate=0.28, away_win_rate=0.33,
        home_advantage_elo=65, home_goal_boost=0.18,
        over_25_rate=0.45, btts_rate=0.45, avg_corners=9.0, corner_home_share=0.52,
        elo_base=1350, elo_spread=120,
        style="technical", notes="日乙主场更弱, 小球倾向"
    ),
    "FIN": LeagueProfile(
        name="芬超", code="FIN", region="europe",
        avg_home_goals=1.45, avg_away_goals=1.15, avg_total_goals=2.60,
        home_win_rate=0.41, draw_rate=0.25, away_win_rate=0.34,
        home_advantage_elo=75, home_goal_boost=0.22,
        over_25_rate=0.50, btts_rate=0.50, avg_corners=9.5, corner_home_share=0.53,
        elo_base=1350, elo_spread=150,
        style="physical", notes="芬兰联赛主场适中, 进球略少"
    ),

    # ── 友谊赛/其他 ──
    "FRIENDLY": LeagueProfile(
        name="友谊赛", code="FRIENDLY", region="world",
        avg_home_goals=1.50, avg_away_goals=1.20, avg_total_goals=2.70,
        home_win_rate=0.42, draw_rate=0.26, away_win_rate=0.32,
        home_advantage_elo=50, home_goal_boost=0.15,
        over_25_rate=0.52, btts_rate=0.52, avg_corners=9.0, corner_home_share=0.52,
        elo_base=1500, elo_spread=300,
        style="mixed", notes="⚠ 友谊赛数据仅供参考, 轮换频繁不可预测"
    ),
}


# ============================================================
# 自适应参数引擎
# ============================================================

def get_profile(league_code: str) -> LeagueProfile:
    """获取联赛画像, 未匹配返回通用默认值"""
    code = league_code.upper()
    if code in LEAGUE_PROFILES:
        return LEAGUE_PROFILES[code]
    # 模糊匹配
    for key, prof in LEAGUE_PROFILES.items():
        if code in key or key in code:
            return prof
    # 默认
    return LeagueProfile(name=league_code, code=code)


def adaptive_params(league_code: str) -> dict[str, Any]:
    """根据联赛画像生成自适应预测参数

    这些参数直接注入蒙特卡洛模拟和泊松预测,
    替代之前硬编码的固定值。

    Returns:
        {
            "home_λ_base": 1.35,       # 用于泊松的主场λ
            "away_λ_base": 1.15,       # 客队λ
            "home_advantage_factor": 0.18,  # 主场进球加成
            "elo_home_bonus": 60,      # ELO主场加分
            "draw_correction": 1.12,   # 平局修正因子 (>1=平局更多)
            "corner_total": 9.2,       # 场均角球
            "corner_home_pct": 0.52,   # 主队角球占比
            "style": "knockout",       # 风格标签
        }
    """
    p = get_profile(league_code)

    return {
        # 泊松λ基础值
        "home_λ_base": round(p.avg_home_goals, 2),
        "away_λ_base": round(p.avg_away_goals, 2),
        "total_λ_base": round(p.avg_total_goals, 2),

        # 主场优势
        "home_advantage_factor": round(p.home_goal_boost, 2),
        "elo_home_bonus": int(p.home_advantage_elo),

        # 平局修正 (实际平局率 / 泊松理论平局率)
        "draw_correction": round(p.draw_rate / 0.25, 2),

        # 角球
        "corner_total": p.avg_corners,
        "corner_home_pct": p.corner_home_share,

        # 市场
        "base_over_25": p.over_25_rate,
        "base_btts": p.btts_rate,

        # ELO
        "elo_base": p.elo_base,
        "elo_spread": p.elo_spread,

        # 联赛风格
        "style": p.style,
        "notes": p.notes,
    }


def compare_league_vs_generic(league_code: str) -> dict[str, Any]:
    """对比联赛自适应参数 vs 通用默认参数

    用于展示自适应带来了多大的差异。
    """
    p = get_profile(league_code)
    generic = LeagueProfile(name="通用默认")

    return {
        "league": p.name,
        "differences": {
            "home_goals": f"{generic.avg_home_goals} → {p.avg_home_goals} ({(p.avg_home_goals/generic.avg_home_goals-1)*100:+.0f}%)",
            "away_goals": f"{generic.avg_away_goals} → {p.avg_away_goals} ({(p.avg_away_goals/generic.avg_away_goals-1)*100:+.0f}%)",
            "home_advantage": f"{generic.home_advantage_elo} → {p.home_advantage_elo} ({p.home_advantage_elo-generic.home_advantage_elo:+d} ELO)",
            "draw_rate": f"{generic.draw_rate:.0%} → {p.draw_rate:.0%} ({(p.draw_rate/generic.draw_rate-1)*100:+.0f}%)",
            "over_25": f"{generic.over_25_rate:.0%} → {p.over_25_rate:.0%}",
            "corners": f"{generic.avg_corners} → {p.avg_corners}",
        },
        "impact": {
            "若用通用模型": f"主场胜率按{generic.home_win_rate:.0%}估算, ELO+{generic.home_advantage_elo}",
            "实际应": f"主场胜率{p.home_win_rate:.0%}, ELO+{p.home_advantage_elo}",
            "偏差后果": f"通用模型会{'高估' if p.home_win_rate < generic.home_win_rate else '低估'}主场优势, 导致{'频繁推荐主队导致亏损' if p.home_win_rate < generic.home_win_rate else '错过主胜机会'}",
        },
    }
