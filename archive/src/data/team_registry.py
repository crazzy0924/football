"""
统一标准化球队ID库

解决痛点:
  "Olympiacos" = "奥林匹亚科斯" = "Olympiakos" = "OLY" → 同一支球队
  开云体育叫"费内巴切", API-Football叫"Fenerbahce", 我们的模型叫"Fenerbahçe"
  → 三个名字, 一个ID。不统一就会数据匹配错乱。

设计:
  - 每支球队一个唯一 team_id (格式: LEAGUE_TEAM, 如 PL_ARS)
  - 收录所有别名 (中文译名/英文全称/英文简称/API简称/博彩网站名)
  - 支持模糊搜索: 输入"费内巴切"或"Fenerbahce"都能匹配到 TUR_FEN
  - 分层赋值: 同联赛新球队自动关联同定位梯队的基准攻防值
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeamRecord:
    """球队统一记录"""
    team_id: str                        # 唯一ID, 如 CLQ_OLY
    primary_name: str                   # 主要中文名, 如 "奥林匹亚科斯"
    aliases: list[str] = field(default_factory=list)  # 所有别名
    league: str = ""                    # 所属联赛代码
    country: str = ""                   # 国家

    # 分层赋值: 基准攻防值 (用于冷启动)
    tier: str = ""                      # 同联赛定位层级: "elite"/"upper"/"mid"/"lower"/"promoted"
    base_attack: float = 1.0            # 基准进攻力 (1.0 = 联赛平均)
    base_defense: float = 1.0           # 基准防守力
    base_elo: float = 1500.0            # 基准ELO

    # 冷启动标记
    is_new_to_league: bool = False      # 欧冠新军? 升班马?
    matches_played_this_season: int = 0 # 本赛季已赛
    cold_start_rounds_remaining: int = 3  # 剩余冷启动轮次

    # 数据溯源
    data_source: str = ""               # "historical_db" / "tier_average" / "manual"
    last_updated: str = ""


# ============================================================
# 全球球队统一注册表
# ============================================================

TEAM_REGISTRY: dict[str, TeamRecord] = {}

def _register(team_id: str, primary: str, aliases: list[str], league: str,
              country: str = "", tier: str = "mid", base_elo: float = 1500,
              is_new: bool = False, source: str = "historical_db") -> None:
    """注册一支球队"""
    TEAM_REGISTRY[team_id] = TeamRecord(
        team_id=team_id, primary_name=primary, aliases=aliases,
        league=league, country=country or league,
        tier=tier, base_elo=base_elo, is_new_to_league=is_new,
        data_source=source,
    )

# ---- 欧冠资格赛 常见球队 ----
_register("CLQ_OLY", "奥林匹亚科斯",
    ["Olympiacos","Olympiakos","Olympiacos Piraeus","OLY","奥林匹亚科斯","奧林比亞高斯"],
    "CLQ", "希腊", "elite", 1580)
_register("CLQ_NEC", "奈梅亨",
    ["NEC Nijmegen","NEC","N.E.C.","奈梅亨","尼美根"],
    "CLQ", "荷兰", "mid", 1460, is_new=True, source="tier_average")
_register("CLQ_FEN", "费内巴切",
    ["Fenerbahce","Fenerbahçe","Fener","FB","费内巴切","費倫巴治"],
    "CLQ", "土耳其", "elite", 1680)
_register("CLQ_STU", "格拉茨风暴",
    ["Sturm Graz","SK Sturm Graz","Sturm","STU","格拉茨风暴","格拉茲風暴"],
    "CLQ", "奥地利", "upper", 1560)
_register("CLQ_SPA", "布拉格斯巴达",
    ["Sparta Prague","Sparta Praha","ACS","SPA","布拉格斯巴达","布拉格斯拉維亞"],
    "CLQ", "捷克", "upper", 1560)
_register("CLQ_LYO", "里昂",
    ["Lyon","Olympique Lyonnais","OL","LYO","里昂","里昂"],
    "CLQ", "法国", "elite", 1680)
_register("CLQ_RSB", "贝尔格莱德红星",
    ["Red Star Belgrade","Crvena Zvezda","FK Crvena Zvezda","RSB","贝尔格莱德红星","貝爾格萊德紅星"],
    "CLQ", "塞尔维亚", "elite", 1600)
_register("CLQ_HBS", "贝尔谢巴夏普尔",
    ["Hapoel Beer Sheva","Hapoel Be'er Sheva","HBS","贝尔谢巴夏普尔","比爾舒華"],
    "CLQ", "以色列", "mid", 1420)
_register("CLQ_BOD", "博德闪耀",
    ["Bodo/Glimt","Bodø/Glimt","FK Bodo/Glimt","BOD","博德闪耀","博多格林特"],
    "CLQ", "挪威", "upper", 1570)
_register("CLQ_USG", "圣吉罗斯",
    ["Union Saint-Gilloise","Union SG","USG","RUSG","圣吉罗斯","聖吉羅斯"],
    "CLQ", "比利时", "upper", 1540)
_register("CLQ_SHA", "沙姆洛克流浪",
    ["Shamrock Rovers","Shamrock","SHA","沙姆洛克流浪","沙姆洛克"],
    "CLQ", "爱尔兰", "mid", 1360)
_register("CLQ_MJA", "米亚尔比",
    ["Mjallby","Mjällby AIF","Mjällby","MJA","米亚尔比","米亞爾比"],
    "CLQ", "瑞典", "lower", 1430, is_new=True, source="tier_average")
_register("CLQ_SLO", "布拉迪斯拉发",
    ["Slovan Bratislava","SK Slovan Bratislava","SLO","布拉迪斯拉发","布拉迪斯拉瓦"],
    "CLQ", "斯洛伐克", "upper", 1500)
_register("CLQ_AGF", "奥胡斯",
    ["AGF","AGF Aarhus","Aarhus","奥胡斯","阿曉斯"],
    "CLQ", "丹麦", "mid", 1520)
_register("CLQ_SAB", "萨巴赫",
    ["Sabah","Sabah FK","Sabah Baku","萨巴赫","沙巴"],
    "CLQ", "阿塞拜疆", "lower", 1430, is_new=True, source="tier_average")
_register("CLQ_FER", "费伦茨瓦罗斯",
    ["Ferencvaros","Ferencvárosi TC","FTC","费伦茨瓦罗斯","費倫斯華路士"],
    "EL", "匈牙利", "upper", 1560)
_register("CLQ_GOR", "扎布热矿工",
    ["Gornik Zabrze","Górnik Zabrze","GOR","扎布热矿工","戈尼克"],
    "EL", "波兰", "mid", 1440)
_register("CLQ_PAN", "帕纳辛纳科斯",
    ["Panathinaikos","PAO","帕纳辛纳科斯","彭拿典奈高斯"],
    "ECL", "希腊", "elite", 1550)
_register("CLQ_CSK", "索菲亚中央陆军1948",
    ["CSKA 1948 Sofia","CSKA 1948","索菲亚中央陆军1948","索菲亞中央陸軍1948"],
    "ECL", "保加利亚", "lower", 1380, is_new=True, source="tier_average")
_register("CLQ_ARR", "亚拉腊",
    ["Ararat-Armenia","FC Ararat-Armenia","亚拉腊","阿拉拉特"],
    "CLQ", "亚美尼亚", "lower", 1380, is_new=True, source="tier_average")
_register("CLQ_CEL", "采列",
    ["NK Celje","Celje","采列","施捷"],
    "CLQ", "斯洛文尼亚", "lower", 1450)
_register("CLQ_LEV", "索菲亚列夫斯基",
    ["Levski Sofia","PFC Levski Sofia","索菲亚列夫斯基","列夫斯基"],
    "CLQ", "保加利亚", "mid", 1480)
_register("CLQ_KAI", "阿拉木图凯拉特",
    ["Kairat Almaty","FC Kairat","阿拉木图凯拉特","凱拉特"],
    "CLQ", "哈萨克斯坦", "lower", 1420, is_new=True, source="tier_average")
_register("CLQ_BRA", "布兰",
    ["Brann","SK Brann","布兰","白蘭恩"],
    "ECL", "挪威", "mid", 1440)
_register("CLQ_APO", "利马索尔阿波罗",
    ["Apollon Limassol","Apollon","利马索尔阿波罗","阿波羅利馬素"],
    "ECL", "塞浦路斯", "mid", 1400)
_register("CLQ_EGN", "伊格纳迪亚",
    ["Egnatia","KF Egnatia","Egnatia Rrogozhine","伊格纳迪亚","埃格納蒂亞"],
    "EL", "阿尔巴尼亚", "lower", 1280, is_new=True, source="tier_average")


# ============================================================
# 查询接口
# ============================================================

def resolve_team(name: str) -> TeamRecord | None:
    """根据任意名称查找球队

    支持: 中文名/英文全称/简称/API名/博彩网站名
    大小写不敏感, 特殊字符容错 (ç→c, ø→o)
    """
    n = name.lower().strip()
    n = n.replace('ç', 'c').replace('ø', 'o').replace('ğ', 'g').replace('ş', 's')

    for team in TEAM_REGISTRY.values():
        # 精确匹配 team_id
        if n == team.team_id.lower():
            return team
        # 匹配主名
        if n == team.primary_name.lower():
            return team
        # 匹配别名
        for alias in team.aliases:
            an = alias.lower().replace('ç', 'c').replace('ø', 'o').replace('ğ', 'g').replace('ş', 's')
            if n == an or n in an or an in n:
                return team

    return None


def get_tier_benchmark(league: str, tier: str) -> dict[str, float]:
    """获取同联赛同层级球队的攻防均值

    用于新球队冷启动: 找不到历史数据时, 用同定位球队的平均值填充。
    例如: 欧冠新军奈梅亨 → 取CLQ中"mid"层级球队的平均进攻力和防守力。
    """
    same_tier = [t for t in TEAM_REGISTRY.values()
                 if t.league == league and t.tier == tier and not t.is_new_to_league]

    if not same_tier:
        return {"attack": 1.0, "defense": 1.0, "elo": 1500.0}

    n = len(same_tier)
    return {
        "attack": round(sum(t.base_attack for t in same_tier) / n, 2),
        "defense": round(sum(t.base_defense for t in same_tier) / n, 2),
        "elo": round(sum(t.base_elo for t in same_tier) / n, 1),
    }
