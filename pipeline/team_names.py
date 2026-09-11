# -*- coding: utf-8 -*-
"""
体彩中文队名 → 英文规范名映射表 (唯一权威源)

fetch_sporttery.py 与 result_fetcher.py 共用;
独立成模块避免导入脚本产生拉取副作用。
"""
from __future__ import annotations

CN_TO_EN_TEAM = {
    '巴黎圣日尔曼': 'Paris SG',
    '阿斯顿维拉': 'Aston Villa',
    '普拉滕斯': 'Platense',
    '科金博联': 'Coquimbo Unido',
    '帕尔梅拉斯': 'Palmeiras',
    '波特诺山丘': 'Cerro Porteno',
    '皇家马德里': 'Real Madrid',
    '巴塞罗那': 'Barcelona',
    '拜仁慕尼黑': 'Bayern Munich',
    '曼城': 'Manchester City',
    '利物浦': 'Liverpool',
    '阿森纳': 'Arsenal',
    '切尔西': 'Chelsea',
    '多特蒙德': 'Borussia Dortmund',
    '国际米兰': 'Inter Milan',
    'AC米兰': 'AC Milan',
    '尤文图斯': 'Juventus',
    '马德里竞技': 'Atletico Madrid',
    '博卡青年': 'Boca Juniors',
    '河床': 'River Plate',
    '弗拉门戈': 'Flamengo',
    '圣保罗': 'Sao Paulo',
    '桑托斯': 'Santos',
    # 欧罗巴资格赛
    '克拉约瓦': 'Universitatea Craiova',
    '克拉约瓦大学': 'Universitatea Craiova',
    '库奥皮奥': 'KuPS',
    '帕福斯': 'Pafos',
    '萨尔茨堡': 'Salzburg',
    '雷克维京': 'Vikingur Reykjavik',
    '雷克雅未克维京人': 'Vikingur Reykjavik',
    '图恩': 'Thun',
    '流浪者': 'Rangers',
    '格拉斯哥流浪者': 'Rangers',
    '比亚韦': 'Jagiellonia',
    '比亚韦斯托克': 'Jagiellonia',
    '安德莱': 'Anderlecht',
    '安德莱赫特': 'Anderlecht',
    '塞萨洛': 'PAOK',
    '塞萨洛尼基': 'PAOK',
    '哈茨': 'Hearts',
    '本菲卡': 'Benfica',
    # 解放者杯
    '米拉索尔': 'Mirassol',
    '基多体大': 'LDU Quito',
    '基多体育大学': 'LDU Quito',
    '罗萨里奥': 'Rosario Central',
    '罗萨里奥中央': 'Rosario Central',
    '科林蒂安': 'Corinthians',
    # 沙特联
    '艾卜哈': 'Abha',
    '拉斯决心': 'Al Hazm',
    '利雅青年': 'Al Shabab',
    '利雅得青年': 'Al Shabab',
    '利雅得青年人': 'Al Shabab',
    '胡巴卡德': 'Al Qadsiah',
    '胡巴尔卡德西亚': 'Al Qadsiah',
    '新未来SC': 'Neom',
    '迈季迈阿宽广': 'Al Majmaah',
    '迈季宽广': 'Al Majmaah',
    '达曼协定': 'Al Ettifaq',
    '利雅得': 'Al Riyadh',
    '利雅得新月': 'Al Hilal',
    '哈马赫费萨利': 'Al Faisaly',
    # 日职/芬超/德乙/瑞超/挪超/荷甲荷乙/法乙/英冠/葡超 (8月14日)
    '东京绿茵': 'Tokyo Verdy',
    '柏太阳神': 'Kashiwa Reysol',
    '瓦萨': 'Vaasan PS',
    'TPS图尔库': 'TPS',
    'TPS图尔': 'TPS',
    '基尔': 'Holstein Kiel',
    '圣保利': 'St Pauli',
    '不伦瑞克': 'Braunschweig',
    '波鸿': 'Bochum',
    '埃尔夫斯堡': 'IF Elfsborg',
    '埃夫斯堡': 'IF Elfsborg',
    '韦斯特罗斯': 'Västerås SK',
    '韦斯特罗': 'Västerås SK',
    '罗森博格': 'Rosenborg',
    '维京': 'Viking FK',
    '特尔斯达': 'Telstar',
    '鹿特丹斯巴达': 'Sparta Rotterdam',
    '鹿斯巴达': 'Sparta Rotterdam',
    '瓦尔韦克': 'Waalwijk',
    '多德勒支': 'Dordrecht',
    '赫拉克勒斯': 'Heracles',
    '赫拉克勒': 'Heracles',
    '登博思': 'Den Bosch',
    '阿纳西': 'Annecy',
    '罗德兹': 'Rodez',
    '兰斯': 'Reims',
    '敦刻尔克': 'Dunkerque',
    '圣埃蒂安': 'St Etienne',
    '克莱蒙': 'Clermont',
    '伍尔弗汉普顿': 'Wolves',
    '伍尔弗': 'Wolves',
    '布莱克本': 'Blackburn',
    '里斯本竞技': 'Sp Lisbon',
    '里斯本': 'Sp Lisbon',
    '吉马良斯': 'Guimaraes',
    # 8月15日 16场补充 (英文名对齐 football-data.org / API-Football)
    '鹿岛鹿角': 'Kashima Antlers', '名古屋鲸八': 'Nagoya Grampus',
    '秋田蓝色闪电': 'Blaublitz Akita', '富山胜利': 'Kataller Toyama',
    '浦和红钻': 'Urawa Red Diamonds', '广岛三箭': 'Sanfrecce Hiroshima',
    '神户胜利船': 'Vissel Kobe', '东京FC': 'FC Tokyo',
    '首尔FC': 'FC Seoul', '大田市民': 'Daejeon Hana Citizen',
    '光州FC': 'Gwangju FC', '浦项制铁': 'Pohang Steelers',
    '柏林赫塔': 'Hertha BSC', '海登海姆': 'FC Heidenheim',
    '威廉二世': 'Willem II', '奈梅亨': 'NEC Nijmegen',
    '阿马多拉': 'Estrela da Amadora',
    '阿尔维卡': 'Alverca',
    '乌德勒支': 'FC Utrecht', '阿尔克马尔': 'AZ Alkmaar',
    '维塞乌': 'Academico Viseu', '圣克拉拉': 'Santa Clara',
    '阿拉维斯': 'Alaves', '赫塔费': 'Getafe',
    'SBV精英': 'Excelsior', 'PSV埃因霍温': 'PSV Eindhoven',
    '福图纳锡塔德': 'Fortuna Sittard', '坎布尔': 'Cambuur',
    '塞维利亚': 'Sevilla', '巴列卡诺': 'Rayo Vallecano',
    '里奥阿维': 'Rio Ave', '波尔图': 'Porto',
    # 8月16日 28场补充 (英文名对齐模型训练库)
    '德岛漩涡': 'Tokushima Vortis', '鸟栖沙岩': 'Sagan Tosu',
    '海牙': 'Den Haag', '格罗宁根': 'Groningen',
    '富川FC': 'Bucheon FC 1995', '全北现代': 'Jeonbuk Motors',
    '仁川联': 'Incheon United', '金泉尚武': 'Gimcheon Sangmu',
    '布鲁马波卡纳': 'IF Brommapojkarna', '厄尔格里特': 'Orgryte',
    '代格福什': 'Degerfors IF', 'IFK哥德堡': 'IFK Goteborg',
    '佐加顿斯': 'Djurgården', 'AIK索尔纳': 'AIK',
    '特温特': 'Twente', '兹沃勒': 'Zwolle',
    '费耶诺德': 'Feyenoord', '前进之鹰': 'Go Ahead Eagles',
    '奥勒松': 'Aalesund', '瓦勒伦加': 'Vålerenga IF',
    '曼彻斯特城': 'Man City',
    'AC奥卢': 'AC Oulu', '国际图尔库': 'Inter Turku',
    '葡萄牙国民': 'Nacional', '埃斯托里尔': 'Estoril',
    '卡尔马': 'Kalmar', '哈马比': 'Hammarby',
    '哥德堡盖斯': 'GAIS', '马尔默': 'Malmo FF',
    '阿贾克斯': 'Ajax', '海伦芬': 'Heerenveen',
    '伯恩利': 'Burnley', '西汉姆联': 'West Ham',
    '桑坦德竞技': 'Santander', '比利亚雷亚尔': 'Villarreal',
    '西班牙人': 'Espanol', '莱万特': 'Levante',
    # 2026-08-17 复盘补录 (体彩中文名 ↔ 外文规范名)
    '拉科鲁尼亚': 'Deportivo La Coruna', '加的夫城': 'Cardiff', '加的夫': 'Cardiff',
    '雷克斯汉姆': 'Wrexham', '巴西国际': 'Internacional', '里莫': 'Remo',
    '卡萨皮亚': 'Casa Pia', '赫根': 'Hacken', '哈尔姆斯塔德': 'Halmstad',
    '赫尔辛基火花': 'Gnistan', '坦佩雷山猫': 'Ilves',
    # 2026-08-20 复盘补录 (08-19 场次队名)
    '马拉加': 'Malaga', '纳什维尔': 'Nashville', '洛杉矶FC': 'Los Angeles FC',
    '博德闪耀': 'Bodo Glimt', '采列': 'Celje', '凯尔特人': 'Celtic',
    'LASK林茨': 'LASK', '纽约红牛': 'NY Red Bulls', '科罗拉多急流': 'Colorado Rapids',
    # 2026-09-09 欧冠补 (修复重复场次: 体彩中文名未桥接, 与赔率API英文名对不上)
    '雅典AEK': 'AEK Athens', '布鲁日': 'Club Brugge KV',
    # 2026-08-22 复盘补录
    '考文垂': 'Coventry', '长崎航海': 'V-Varen Nagasaki', '千叶市原': 'JEF United Chiba',
    '拉赫蒂': 'Lahti', '塞伊奈约基': 'SJK Seinajoki', '吉达联合': 'Al Ittihad',
    # 2026-08-24 复盘补录
    '弗洛西诺内': 'Frosinone', '威尼斯': 'Venezia',
    '阿罗卡': 'Arouca', '摩雷伦斯': 'Moreirense',
    '腓特烈斯塔': 'Fredrikstad FK', '克里斯蒂安松': 'Kristiansund',
    '瓦斯科达伽马': 'Vasco da Gama', '法马利康': 'Famalicao',
    '马里迪莫': 'Maritimo', '布拉加': 'Sp Braga',
    '吉维森特': 'Gil Vicente', '纽约城': 'New York City',
    '费城联合': 'Philadelphia Union', '莫尔德': 'Molde',
    '特罗姆瑟': 'Tromso', '布兰': 'Brann',
    '汉坎': 'HamKam', '萨尔普斯堡': 'Sarpsborg 08',
    '桑纳菲尤尔': 'Sandefjord',
}
# ═══════════════════════════════════════════════════════
# 五大联赛完整对照 (2026-08-16 · 从模型训练库导出精确英文名)
# 体彩中文名 → 模型内部名; update() 后写覆盖前写
# ═══════════════════════════════════════════════════════
CN_TO_EN_TEAM.update({
    # ── 英超 PL ──
    '阿森纳': 'Arsenal', '维拉': 'Aston Villa', '伯恩茅斯': 'Bournemouth',
    '布伦特福德': 'Brentford', '布莱顿': 'Brighton',
    '水晶宫': 'Crystal Palace', '埃弗顿': 'Everton', '富勒姆': 'Fulham',
    '利兹联': 'Leeds', '曼城': 'Man City', '曼联': 'Man United',
    '纽卡斯尔': 'Newcastle', '纽卡斯尔联': 'Newcastle',
    '诺丁汉森林': "Nott'm Forest", '诺丁汉': "Nott'm Forest",
    '桑德兰': 'Sunderland', '热刺': 'Tottenham',
    '狼队': 'Wolves',
    # ── 英冠 ELC ──
    '斯旺西': 'Swansea', '沃特福德': 'Watford', '朴次茅斯': 'Portsmouth',
    '德比郡': 'Derby', '林肯城': 'Lincoln', '普雷斯顿': 'Preston',
    '布里斯托尔城': 'Bristol City', '谢菲尔德联': 'Sheffield United', '谢菲联': 'Sheffield United',
    '博尔顿': 'Bolton', '伯明翰': 'Birmingham', '南安普敦': 'Southampton',
    '斯托克城': 'Stoke', '诺维奇': 'Norwich', '西布朗': 'West Brom',
    '考文垂': 'Coventry', '米尔沃尔': 'Millwall', '卡迪夫城': 'Cardiff',
    '赫尔城': 'Hull', '卢顿': 'Luton', '伯恩利': 'Burnley',
    '米德尔斯堡': 'Middlesbrough', '牛津联': 'Oxford', '谢周三': 'Sheffield Weds',
    '普利茅斯': 'Plymouth', '查尔顿': 'Charlton', '雷克瑟姆': 'Wrexham',
    # ── 西甲 PD ──
    '毕尔巴鄂竞技': 'Ath Bilbao', '毕尔巴鄂': 'Ath Bilbao',
    '马德里竞技': 'Ath Madrid', '马竞': 'Ath Madrid',
    '皇家贝蒂斯': 'Betis', '贝蒂斯': 'Betis',
    '塞尔塔': 'Celta', '维戈塞尔塔': 'Celta',
    '埃尔切': 'Elche', '赫罗纳': 'Girona',
    '马洛卡': 'Mallorca', '马略卡': 'Mallorca',
    '奥萨苏纳': 'Osasuna', '奥维耶多': 'Oviedo',
    '皇家社会': 'Sociedad', '瓦伦西亚': 'Valencia',
    '巴列卡诺': 'Vallecano', '皇家马德里': 'Real Madrid', '皇马': 'Real Madrid',
    # ── 德甲 BL1 ──
    '奥格斯堡': 'Augsburg', '拜仁慕尼黑': 'Bayern Munich', '拜仁': 'Bayern Munich',
    '多特蒙德': 'Dortmund', '多特': 'Dortmund',
    '法兰克福': 'Ein Frankfurt', '科隆': 'FC Koln',
    '弗赖堡': 'Freiburg', '汉堡': 'Hamburg',
    '海登海姆': 'Heidenheim', '霍芬海姆': 'Hoffenheim',
    '勒沃库森': 'Leverkusen', '门兴格拉德巴赫': "M'gladbach", '门兴': "M'gladbach",
    '美因茨': 'Mainz', '莱比锡红牛': 'RB Leipzig', '莱比锡': 'RB Leipzig',
    '斯图加特': 'Stuttgart', '柏林联合': 'Union Berlin',
    '云达不莱梅': 'Werder Bremen', '不莱梅': 'Werder Bremen',
    '沃尔夫斯堡': 'Wolfsburg',
    # ── 意甲 SA ──
    '亚特兰大': 'Atalanta', '博洛尼亚': 'Bologna', '卡利亚里': 'Cagliari',
    '科莫': 'Como', '克雷莫纳': 'Cremonese', '佛罗伦萨': 'Fiorentina',
    '热那亚': 'Genoa', '拉齐奥': 'Lazio', '莱切': 'Lecce',
    'AC米兰': 'Milan', '那不勒斯': 'Napoli', '帕尔马': 'Parma',
    '比萨': 'Pisa', '罗马': 'Roma', '萨索洛': 'Sassuolo',
    '都灵': 'Torino', '乌迪内斯': 'Udinese', '维罗纳': 'Verona',
    # ── 法甲 FL1 ──
    '昂热': 'Angers', '欧塞尔': 'Auxerre', '波尔多': 'Bordeaux',
    '布雷斯特': 'Brest', '勒阿弗尔': 'Le Havre', '朗斯': 'Lens',
    '里尔': 'Lille', '洛里昂': 'Lorient', '里昂': 'Lyon',
    '马赛': 'Marseille', '梅斯': 'Metz', '摩纳哥': 'Monaco',
    '南特': 'Nantes', '尼斯': 'Nice', '巴黎FC': 'Paris FC',
    '巴黎圣日耳曼': 'Paris SG', '雷恩': 'Rennes',
    '斯特拉斯堡': 'Strasbourg', '图卢兹': 'Toulouse',
    # ── 2026-09-06 补 (复盘对账缺失的体彩中文名变体/升班马) ──
    '曼彻斯特联': 'Man United', '托特纳姆热刺': 'Tottenham', '托特纳姆': 'Tottenham',
    '伊普斯维奇': 'Ipswich', '云达不来梅': 'Werder Bremen',
    '埃尔沃斯堡': 'Elversberg', '帕德博恩': 'Paderborn',
    '沙尔克04': 'Schalke 04', '沙尔克': 'Schalke 04',
    '蒙扎': 'Monza', '特鲁瓦': 'Troyes', '巴伦西亚': 'Valencia',
    # ── 欧冠补漏 (2026-09-10, 体彩中文名) ──
    '布拉格斯拉维亚': 'Slavia Prague', '斯拉维亚': 'Slavia Prague',
    '莱比锡红牛': 'RB Leipzig', '科莫': 'Como', '朗斯': 'Lens',
    '萨巴赫': 'Sabah',
})


# ═══════════════════════════════════════════════════════
# 英文别名 → 中性规范名 (2026-09-10 · 赛果源桥接)
# 背景: 复盘改用 football-data.org 做赛果源后, 其队名("Sporting CP"/"PAE AEK"/
# "Paris Saint-Germain FC")与本系统规范名("Sp Lisbon"/"雅典AEK"/"Paris SG")
# 对不上 → 匹配失败。此表把两侧都归一到同一个中性名再比较。
# ═══════════════════════════════════════════════════════
def _alias_key(s: str) -> str:
    """别名查表键: 去重音 + 小写 + 去空格/点/撇号。"""
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(' ', '').replace('.', '').replace("'", '')


_EN_ALIAS_RAW = {
    # 雅典AEK
    '雅典AEK': 'AEK Athens', 'PAE AEK': 'AEK Athens', 'AEK Athens': 'AEK Athens',
    # 里斯本竞技
    'Sp Lisbon': 'Sporting Lisbon', 'Sporting CP': 'Sporting Lisbon',
    'Sporting Lisbon': 'Sporting Lisbon', 'Sporting Clube de Portugal': 'Sporting Lisbon',
    # 巴黎圣日耳曼
    'Paris SG': 'Paris Saint-Germain', 'Paris Saint-Germain FC': 'Paris Saint-Germain',
    'Paris Saint-Germain': 'Paris Saint-Germain',
    # 布拉迪斯拉发
    '布拉迪斯拉发': 'Slovan Bratislava', 'SK Slovan Bratislava': 'Slovan Bratislava',
    'Slovan Bratislava': 'Slovan Bratislava',
    # 欧冠常见对手 (2026-09-10 复盘用)
    '加拉塔萨雷': 'Galatasaray', 'Galatasaray SK': 'Galatasaray',
    '费内巴切': 'Fenerbahce', 'Fenerbahce SK': 'Fenerbahce',
    '萨巴赫': 'Sabah', 'Sabah FK': 'Sabah',
    '布拉格斯拉维亚': 'Slavia Prague', 'SK Slavia Praha': 'Slavia Prague',
    'Slavia Prague': 'Slavia Prague', '斯拉维亚': 'Slavia Prague',
    '朗斯': 'Lens', 'RC Lens': 'Lens',
    '科莫': 'Como', 'Como 1907': 'Como',
    '莱比锡红牛': 'RB Leipzig', '博德闪耀': 'Bodo Glimt', 'Bodo/Glimt': 'Bodo Glimt',
    # 常见前后缀变体(football-data.org 全名 → 本系统规范名)
    'FC Internazionale Milano': 'Inter', 'Internazionale': 'Inter',
    'Club Brugge KV': 'Club Brugge', 'Bayern Munchen': 'Bayern Munich',
    'Manchester City FC': 'Man City', 'Manchester United FC': 'Man United',
    'Villarreal CF': 'Villarreal', 'Real Betis Balompie': 'Betis',
    'Lille OSC': 'Lille', 'FC Porto': 'Porto', 'FC Barcelona': 'Barcelona',
    'SSC Napoli': 'Napoli', 'Arsenal FC': 'Arsenal', 'Liverpool FC': 'Liverpool',
    'VfB Stuttgart': 'Stuttgart', 'Feyenoord Rotterdam': 'Feyenoord',
    'Sport Lisboa e Benfica': 'Benfica',
}

EN_TEAM_ALIASES = {_alias_key(k): v for k, v in _EN_ALIAS_RAW.items()}


def resolve_team_alias(name: str) -> str | None:
    """查英文别名表, 命中返回中性规范名, 否则 None。"""
    if not name:
        return None
    return EN_TEAM_ALIASES.get(_alias_key(name))


# ═══════════════════════════════════════════════════════
# 体彩 TeamId 主键映射 (2026-09-10 · 治本方案)
# 背景: 体彩给的中文名是缩写且会变("布拉格斯拉维亚"→"斯拉维亚",
# "莱比锡红牛"→"莱红牛"), 靠名字翻译必然漏; 但体彩每队都给稳定的数字
# TeamId。故以 TeamId 为主键, 维护"体彩TeamId → 本系统规范英文名",
# 一旦学会就永久绑定, 中文名再变也不影响。
# ═══════════════════════════════════════════════════════
import json as _json
import os as _os

_TEAM_ID_MAP_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "data", "state", "team_id_map.json",
)

_TEAM_ID_MAP: dict[str, str] | None = None


def load_team_id_map() -> dict:
    """读取体彩TeamId→规范英文名映射(带缓存)。"""
    global _TEAM_ID_MAP
    if _TEAM_ID_MAP is None:
        try:
            with open(_TEAM_ID_MAP_PATH, "r", encoding="utf-8") as f:
                _TEAM_ID_MAP = _json.load(f)
        except Exception:
            _TEAM_ID_MAP = {}
    return _TEAM_ID_MAP


def save_team_id_map() -> None:
    """落盘映射表(按ID排序, 便于人工维护)。"""
    m = load_team_id_map()
    _os.makedirs(_os.path.dirname(_TEAM_ID_MAP_PATH), exist_ok=True)
    with open(_TEAM_ID_MAP_PATH, "w", encoding="utf-8") as f:
        _json.dump({k: m[k] for k in sorted(m, key=lambda x: int(x))}, f, ensure_ascii=False, indent=1)


def _has_cjk(s: str) -> bool:
    """判断字符串是否含中文(即尚未翻译)。"""
    return any("\u4e00" <= c <= "\u9fff" for c in (s or ""))


def resolve_team(cn_name: str, team_id=None, en_code: str = "") -> tuple[str, str]:
    """体彩队名 → 本系统规范英文名。

    优先级: ① TeamId 命中映射表(最稳) ② 中文名映射(命中则学习到ID) ③ 原名兜底。
    自愈: 若ID上绑的还是中文(先前未收录), 而现已补了中文映射, 就地订正。
    返回 (规范名, 来源标签), 来源标签用于统计漏配率。
    """
    m = load_team_id_map()
    key = str(team_id) if team_id not in (None, "", 0, "0") else ""
    cn = (cn_name or "").strip()

    if key and key in m:
        cur = m[key]
        if _has_cjk(cur) and cn in CN_TO_EN_TEAM:
            m[key] = CN_TO_EN_TEAM[cn]      # 订正历史脏绑定
            return m[key], "id-fix"
        return cur, "id"
    if cn in CN_TO_EN_TEAM:
        canonical = CN_TO_EN_TEAM[cn]
        if key:
            m[key] = canonical
        return canonical, "cn"

    # 英文名原样(体彩偶尔直接给英文)
    if cn and not _has_cjk(cn):
        if key:
            m[key] = cn
        return cn, "en"

    if key and key not in m:
        m[key] = cn  # 先绑定原名, 后续人工订正映射表即可永久生效
    return cn, "unresolved"

# ================================================================
# 队名模糊匹配 (2026-09-11)
# 统一给 pipeline.py 的 SofaScore 盘口匹配、result_fetcher 的赛果匹配使用。
# 只认 token 精确相同 —— 放开子串会造成假配对:
#   Sevilla       ↔ Aston Villa      (villa ⊂ sevilla)
#   Stade Rennais ↔ Stade Brestois   (stade)
# 假配对比匹配不上危险得多: 会把别场的盘口/比分挂到这一场。
# ================================================================

# 无区分度词: 俱乐部后缀 + 通用前缀。
# 刻意不含 racing/union/city —— 它们在 Racing Santander / Union Berlin 里是识别词。
TEAM_STOP = frozenset({
    'fc', 'cf', 'sc', 'afc', 'sk', 'fk', 'ac', 'as', 'ss', 'cd', 'sv', 'us',
    'vfb', 'vfl', 'tsg', 'bsc', 'osc', 'club', 'de', 'cp', 'acf', 'ssc', 'rc',
    'real', 'stade', 'deportivo', 'olympique', 'atletico', 'athletic', 'sporting',
})

# 非拉丁字母显式转写 (NFKD 不会把 ø 拆成 o)
_TEAM_TRANSLIT = {
    'ø': 'o', 'Ø': 'o', 'đ': 'd', 'ð': 'd', 'ł': 'l', 'ß': 'ss',
    'æ': 'ae', 'œ': 'oe', 'þ': 'th', 'ı': 'i', 'ŋ': 'n',
}


def team_tokens(name: str) -> frozenset[str]:
    """队名 → 模糊匹配用 token 集合 (转写/去重音/去通用词/去数字)。

    覆盖: Man United↔Manchester United、Dortmund↔Borussia Dortmund、
          Bodo Glimt↔FK Bodø/Glimt、Bayern Munich↔FC Bayern München
    """
    import re as _re
    import unicodedata as _ud
    s = str(name or '')
    for _k, _v in _TEAM_TRANSLIT.items():
        s = s.replace(_k, _v)
    s = _ud.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not _ud.combining(c))
    s = _re.sub(r'[^a-z ]', ' ', s)
    return frozenset(t for t in s.split() if len(t) >= 3 and t not in TEAM_STOP)


def team_score(a: str, b: str) -> int:
    """两个队名的共享 token 数 (只认精确相同)。"""
    return len(team_tokens(a) & team_tokens(b))

# ================================================================
# 队名总表 (2026-09-11)
# data/state/team_name_map.json: 体彩中文名 <-> SofaScore 名 <-> 我们的规范名
# 由 tools/build_team_map.py 生成。匹配时**优先查表**, 查不到才退回 token 打分 ——
# 表是人工确认过的, 比任何模糊算法都可靠。
# ================================================================

_TEAM_MAP_CACHE: dict | None = None


def load_team_name_map(path: str | None = None) -> dict:
    """加载总表 → {任意一侧的名字: 我们的规范名}。"""
    global _TEAM_MAP_CACHE
    if _TEAM_MAP_CACHE is not None and path is None:
        return _TEAM_MAP_CACHE
    import json as _json
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    p = path or _os.path.join(root, 'data', 'state', 'team_name_map.json')
    idx: dict = {}
    try:
        with open(p, encoding='utf-8') as fh:
            doc = _json.load(fh)
        rows = doc.get('rows') or []
        # 别名归一: SofaScore 名单里同一队可能有两行 (RC Lens / Racing Club de Lens),
        # 先把别名指向的主名收集起来, 保证每个名字最终都归到同一个规范名。
        alias_of: dict = {}
        for r in rows:
            c = r.get('canonical')
            if not c:
                continue
            for a in r.get('canonical_aliases') or []:
                if a != c:
                    alias_of[a] = c

        def _norm(c: str) -> str:
            seen = set()
            while c in alias_of and c not in seen:
                seen.add(c)
                c = alias_of[c]
            return c

        for r in rows:
            c = r.get('canonical')
            if not c:
                continue
            c = _norm(c)
            if r.get('sofascore'):
                idx[r['sofascore']] = c
            for a in r.get('canonical_aliases') or []:
                idx[a] = c
        # 赛果/预测侧的写法 (FC Bayern München / Fenerbahçe SK ...)
        for nm, c in (doc.get('result_names') or {}).items():
            idx.setdefault(nm, _norm(c))
    except Exception:
        pass
    if path is None:
        _TEAM_MAP_CACHE = idx
    return idx


def canonical_of(name: str) -> str | None:
    """把任意一侧的名字归到我们的规范名; 查不到返回 None。"""
    if not name:
        return None
    return load_team_name_map().get(name)



