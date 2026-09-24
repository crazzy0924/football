# -*- coding: utf-8 -*-
"""国家队预测 —— 与俱乐部链路(五大联赛+欧冠)物理隔离的独立子系统。

为什么独立 (2026-09-24 用户拍板):
  - 国家队每年只有 ~10 场, 且每期集训名单都在换人, 与俱乐部的 DC 攻防参数
    是两种完全不同的东西, 混在一起会互相污染。
  - 本包不 import pipeline/ 或 models/dixon_coles.py 里的有状态类, 只复用纯函数。
  - 范围: 欧国联 League A (16 队)。B/C/D 级不做 (用户 2026-09-24 决定)。
"""

LEAGUE_A_2026_27 = {
    "A1": ["France", "Italy", "Belgium", "Turkey"],
    "A2": ["Germany", "Netherlands", "Serbia", "Greece"],
    "A3": ["Spain", "Croatia", "England", "Czech Republic"],
    "A4": ["Portugal", "Denmark", "Norway", "Wales"],
}

# 体彩中文名 -> 语料英文名 (只覆盖 League A 16 队)
CN_TO_EN = {
    "法国": "France", "意大利": "Italy", "比利时": "Belgium", "土耳其": "Turkey",
    "德国": "Germany", "荷兰": "Netherlands", "塞尔维亚": "Serbia", "希腊": "Greece",
    "西班牙": "Spain", "克罗地亚": "Croatia", "英格兰": "England", "捷克": "Czech Republic",
    "葡萄牙": "Portugal", "丹麦": "Denmark", "挪威": "Norway", "威尔士": "Wales",
}
EN_TO_CN = {v: k for k, v in CN_TO_EN.items()}

ALL_A_TEAMS = [t for g in LEAGUE_A_2026_27.values() for t in g]