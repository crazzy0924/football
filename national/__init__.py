# -*- coding: utf-8 -*-
"""国家队预测 —— 与俱乐部链路(五大联赛+欧冠)物理隔离的独立子系统。

为什么独立 (2026-09-24 用户拍板):
  - 国家队每年只有 ~10 场, 且每期集训名单都在换人, 与俱乐部的 DC 攻防参数
    是两种完全不同的东西, 混在一起会互相污染。
  - 本包不 import pipeline/ 或 models/dixon_coles.py 里的有状态类, 只复用纯函数。

范围 (2026-09-26 用户更新):
  - 2026-09-24 原定: 只做 League A (16 队)。
  - **2026-09-26 用户拍板扩大: "C 级比赛一样要做预测"** → 代码不再按级别过滤,
    凡体彩挂出的欧国联场次 (A/B/C 级) 一律纳入。**联赛级别只影响显示, 不影响模型。**
  - 因此下面的 `LEAGUE_A_2026_27` **不再是准入名单**, 只用于显示组别。
    真正决定能不能进预测的是 `CN_TO_EN` —— 体彩中文名能查到英文名就做。

⚠️ 分组信息只核实到 League A (2026-02 抽签, BBC/AP 报道):
     A1 法国/意大利/比利时/土耳其 · A2 德国/荷兰/塞尔维亚/希腊
     A3 西班牙/克罗地亚/英格兰/捷克   · A4 葡萄牙/丹麦/挪威/威尔士
   B/C 级的**分组**尚未拿到权威源 (本机 Wikipedia/UEFA 直连超时, 全网搜索是代理不给正文),
   所以 B/C 只登记"已知参赛队"(从体彩在售场次抽出来的), **不编造组号**。
   拿到官方抽签结果后补: 组号只喂给提示词, 补上前后预测结果不受影响。
"""

# ---------------------------------------------------------------------------
# League A 分组 (2026/27, 已核实)
# ---------------------------------------------------------------------------
LEAGUE_A_2026_27 = {
    "A1": ["France", "Italy", "Belgium", "Turkey"],
    "A2": ["Germany", "Netherlands", "Serbia", "Greece"],
    "A3": ["Spain", "Croatia", "England", "Czech Republic"],
    "A4": ["Portugal", "Denmark", "Norway", "Wales"],
}

# ---------------------------------------------------------------------------
# B / C 级: 只登记"已知参赛队", 组号待核实 (来源: 体彩在售场次 + 常识)
# ---------------------------------------------------------------------------
TEAMS_B_KNOWN = [
    "Scotland", "Slovenia", "Ukraine", "Sweden", "Romania", "Slovakia",
    "Israel", "Republic of Ireland", "Northern Ireland",
    "Bosnia and Herzegovina", "Albania", "Georgia", "Austria", "Hungary",
    "Finland", "Montenegro", "Switzerland",
]
TEAMS_C_KNOWN = [
    "Faroes", "Kazakhstan", "Iceland", "Estonia", "Bulgaria", "Luxembourg",
    "North Macedonia", "Armenia", "Azerbaijan", "Belarus", "Cyprus",
    "Latvia", "Lithuania",
]

# ---------------------------------------------------------------------------
# 体彩中文名 -> 语料英文名
# 国名/队名一律照 `national/corpus.py` 的语料拼写**逐字抄** —— 差一个字母就静默丢场次。
# 体彩用的是**截断简称**(斯洛文尼/哈萨克/波黑/北马其顿), 必须按体彩写法登记。
# ---------------------------------------------------------------------------
CN_TO_EN = {
    # --- A 级 16 队 (原有) ---
    "法国": "France", "意大利": "Italy", "比利时": "Belgium", "土耳其": "Turkey",
    "德国": "Germany", "荷兰": "Netherlands", "塞尔维亚": "Serbia", "希腊": "Greece",
    "西班牙": "Spain", "克罗地亚": "Croatia", "英格兰": "England", "捷克": "Czech Republic",
    "葡萄牙": "Portugal", "丹麦": "Denmark", "挪威": "Norway", "威尔士": "Wales",
    # --- 2026-09-26 扩大范围新增 (今日在售 10 个 + 同级可能出场) ---
    "斯洛文尼": "Slovenia", "斯洛文尼亚": "Slovenia",
    "苏格兰": "Scotland",
    "法罗群岛": "Faroe Islands",
    "哈萨克": "Kazakhstan", "哈萨克斯坦": "Kazakhstan",
    "冰岛": "Iceland", "爱沙尼亚": "Estonia",
    "保加利亚": "Bulgaria", "卢森堡": "Luxembourg",
    "北马其顿": "North Macedonia", "瑞士": "Switzerland",
    "乌克兰": "Ukraine", "瑞典": "Sweden", "罗马尼亚": "Romania", "斯洛伐克": "Slovakia",
    "以色列": "Israel", "爱尔兰": "Republic of Ireland",
    "北爱尔兰": "Northern Ireland", "波黑": "Bosnia and Herzegovina",
    "阿尔巴尼亚": "Albania", "格鲁吉亚": "Georgia", "奥地利": "Austria",
    "匈牙利": "Hungary", "芬兰": "Finland", "黑山": "Montenegro",
    "亚美尼亚": "Armenia", "阿塞拜疆": "Azerbaijan", "白俄罗斯": "Belarus",
    "塞浦路斯": "Cyprus", "拉脱维亚": "Latvia", "立陶宛": "Lithuania",
}
EN_TO_CN = {v: k for k, v in CN_TO_EN.items()}

# 兼容旧引用 (run_nl.py 用): A 级 16 队
ALL_A_TEAMS = [t for g in LEAGUE_A_2026_27.values() for t in g]

# 已知的全部欧国联参赛队 (A + B + C 已知), 供自检/覆盖率用
ALL_KNOWN_TEAMS = ALL_A_TEAMS + TEAMS_B_KNOWN + TEAMS_C_KNOWN
