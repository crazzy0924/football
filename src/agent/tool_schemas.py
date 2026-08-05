"""
Anthropic 工具定义 Schema

严格按照 Anthropic API tool_use 格式定义
每个工具包含 name, description, input_schema
"""
from __future__ import annotations

# ============================================================
# Anthropic Function Calling Tool Schemas
# ============================================================

TOOLS_SCHEMA = [
    {
        "name": "search_knowledge_base",
        "description": """搜索足球战术知识库，获取专业分析文章和战术概念解释。

知识库包含:
- 战术体系分析 (高位逼抢、边后卫内收、三中卫体系等)
- 经典比赛复盘 (欧冠决赛、重要德比战术解析)
- 教练理念与方法论
- 数据模型解析 (xG、PPDA、Packing 等)

当用户问到 "为什么..."、"什么是..."、"如何破解..." 等需要专业知识的问题时，
优先调用此工具获取战术理论支持，再结合实时数据作答。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询 (自然语言，如 '曼城边后卫内收战术原理' 或 '高位逼抢的弱点')",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回文档数量 (默认 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_matches",
        "description": "搜索指定联赛的即将进行或近期的比赛。返回比赛列表，包含球队名称、比赛时间、比赛ID等信息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "competition": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1", "CL", "ELC", "DED", "PPL"],
                    "description": "联赛代码: PL=英超, PD=西甲, BL1=德甲, SA=意甲, FL1=法甲, CL=欧冠",
                },
                "matchday": {
                    "type": "integer",
                    "description": "比赛轮次 (可选, 不填则返回最新一轮)",
                },
            },
            "required": ["competition"],
        },
    },
    {
        "name": "predict_match",
        "description": """预测单场足球比赛结果。使用泊松分布模型和ELO评分系统，综合分析以下因素：
- 球队攻防实力指数
- ELO 评分差异
- 近期状态 (近5场战绩)
- 主客场优势
返回胜平负概率、最可能比分、大小球概率、双方进球概率等详细数据。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "home_team": {
                    "type": "string",
                    "description": "主队名称 (英文全名, 如 'Arsenal', 'Manchester City')",
                },
                "away_team": {
                    "type": "string",
                    "description": "客队名称 (英文全名, 如 'Liverpool', 'Chelsea')",
                },
                "home_goals_scored": {
                    "type": "number",
                    "description": "主队本赛季场均进球数 (可选, 不填则根据ELO自动推算)",
                },
                "home_goals_conceded": {
                    "type": "number",
                    "description": "主队本赛季场均失球数 (可选)",
                },
                "away_goals_scored": {
                    "type": "number",
                    "description": "客队本赛季场均进球数 (可选)",
                },
                "away_goals_conceded": {
                    "type": "number",
                    "description": "客队本赛季场均失球数 (可选)",
                },
                "home_form": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["W", "D", "L"]},
                    "description": "主队近期5场比赛战绩, 如 ['W','W','D','L','W'] (可选)",
                },
                "away_form": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["W", "D", "L"]},
                    "description": "客队近期5场比赛战绩, 如 ['L','D','W','W','L'] (可选)",
                },
            },
            "required": ["home_team", "away_team"],
        },
    },
    {
        "name": "get_team_statistics",
        "description": """获取球队本赛季详细统计数据，包括：
- 场均进球/失球
- 射门数、射正数
- 控球率
- 零封场次、未进球场次
- 近期状态 (W/D/L)
这些数据可用于提高比赛预测的准确性。
建议：在调用 predict_match 之前先用此工具获取两队真实数据。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "球队名称 (英文全名, 如 'Arsenal')",
                },
                "competition": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1", "CL"],
                    "description": "联赛代码",
                },
                "season": {
                    "type": "integer",
                    "description": "赛季年份 (如 2025, 不填则用当前年份)",
                },
            },
            "required": ["team_name", "competition"],
        },
    },
    {
        "name": "get_standings",
        "description": "获取指定联赛的当前积分榜排名，包含各队的比赛场次、胜平负、进球失球和积分。",
        "input_schema": {
            "type": "object",
            "properties": {
                "competition": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1"],
                    "description": "联赛代码",
                },
            },
            "required": ["competition"],
        },
    },
    {
        "name": "get_team_info",
        "description": "获取指定球队的详细信息，包括 ELO 评分、实力等级评估、球队分析等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "球队名称 (英文全名)",
                },
            },
            "required": ["team_name"],
        },
    },
    {
        "name": "analyze_head_to_head",
        "description": "分析两支球队的历史交锋记录，包括胜平负统计和胜率分析。",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_a": {
                    "type": "string",
                    "description": "球队 A 名称",
                },
                "team_b": {
                    "type": "string",
                    "description": "球队 B 名称",
                },
            },
            "required": ["team_a", "team_b"],
        },
    },
    {
        "name": "get_match_odds",
        "description": """获取比赛赔率数据，包括:
- 多家博彩公司欧赔 (1X2) 平均 & 最佳赔率
- Margin 剥离后的市场隐含概率 (Shin 方法)
- 必发指数 (Betfair Index) 或赔率反推指数
- 赔率来源与更新时间
赔率反映了市场对比赛结果的集体判断，可与模型预测交叉验证。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "home_team": {
                    "type": "string",
                    "description": "主队名称",
                },
                "away_team": {
                    "type": "string",
                    "description": "客队名称",
                },
                "competition": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1"],
                    "description": "联赛代码",
                },
            },
            "required": ["home_team", "away_team"],
        },
    },
    {
        "name": "compare_model_vs_market",
        "description": """模型 vs 市场赔率 价值对比 (核心工具)。

自动完成:
1. 调用模型预测 (泊松 + ELO) → 模型概率
2. 拉取市场赔率 → 真实隐含概率 (margin 剥离)
3. 计算价值偏差 + 凯利投注比例
4. 输出 "模型推荐 vs 市场看好" 的一致性判断

当模型概率显著高于市场隐含概率时，可能存在价值投注机会。
建议在 predict_match 之后调用此工具，获取完整的模型-市场对比。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "home_team": {
                    "type": "string",
                    "description": "主队名称",
                },
                "away_team": {
                    "type": "string",
                    "description": "客队名称",
                },
                "competition": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1"],
                    "description": "联赛代码",
                },
            },
            "required": ["home_team", "away_team"],
        },
    },
    {
        "name": "review_yesterday_matches",
        "description": """复盘昨日比赛 —— 模型 vs 真实赛果 vs Kambi 赔率全对比。

自动完成:
1. 获取昨日完赛比分
2. 逐场重跑模型预测
3. 计算 Brier Score / Log Loss / 准确率
4. 对比 Kambi 市场赔率
5. 检测系统性偏差 (主场高估/平局低估)
6. 生成模型调整建议 (ELO系数/平局扩展因子等)

建议每天赛后运行一次，持续校准模型。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "league": {
                    "type": "string",
                    "enum": ["PL", "PD", "BL1", "SA", "FL1"],
                    "description": "联赛代码",
                },
            },
            "required": [],
        },
    },
    {
        "name": "backtest_match",
        "description": "单场比赛回测 —— 输入真实比分，检查模型预测是否准确。输出偏差分析和Brier Score。",
        "input_schema": {
            "type": "object",
            "properties": {
                "home_team": {"type": "string", "description": "主队名称"},
                "away_team": {"type": "string", "description": "客队名称"},
                "home_goals": {"type": "integer", "description": "主队实际进球"},
                "away_goals": {"type": "integer", "description": "客队实际进球"},
            },
            "required": ["home_team", "away_team", "home_goals", "away_goals"],
        },
    },
]
