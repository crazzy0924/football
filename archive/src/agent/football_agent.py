"""
足球分析智能体 - 核心调度模块

使用 Anthropic API + Function Calling 实现:
1. 用户提出足球相关问题
2. Claude 分析意图, 决定调用哪些工具
3. 工具执行后返回数据
4. Claude 综合分析并生成专业回答
"""
from __future__ import annotations

import json
from typing import Any

import anthropic
from loguru import logger

from src.agent.tools import (
    analyze_head_to_head,
    backtest_match,
    compare_model_vs_market,
    get_match_odds,
    get_standings,
    get_team_info,
    get_team_statistics,
    predict_match,
    review_yesterday_matches,
    search_knowledge_base,
    search_matches,
)
from src.agent.tool_schemas import TOOLS_SCHEMA
from src.utils.config import config

# ============================================================
# 工具路由表
# ============================================================

TOOL_HANDLERS = {
    "search_matches": search_matches,
    "predict_match": predict_match,
    "get_team_statistics": get_team_statistics,
    "get_standings": get_standings,
    "get_team_info": get_team_info,
    "analyze_head_to_head": analyze_head_to_head,
    "search_knowledge_base": search_knowledge_base,
    "get_match_odds": get_match_odds,
    "compare_model_vs_market": compare_model_vs_market,
    "review_yesterday_matches": review_yesterday_matches,
    "backtest_match": backtest_match,
}

# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """# 角色定义

你是一名持有 **UEFA Pro 执照** 的足球分析师，拥有 15 年以上顶级联赛战术分析经验。
你擅长**数据驱动的战术解读**，能够将统计模型（泊松分布、ELO 评分、xG）与传统战术
分析（阵型、对位、阶段转换）相结合，给出专业、客观、有洞察力的比赛研判。

你同时可以访问一个**足球战术知识库**，其中包含大量战术分析文章、经典比赛复盘
和教练访谈。当用户问到战术概念（如"边后卫内收"、"高位逼抢触发点"）时，
你应该优先检索知识库，用战术理论支撑你的回答。

---

# 输出格式规范

当回答比赛分析类问题时，**必须**遵循以下三段式结构：

## 第一步：结论先行
用 2-3 句话给出核心判断。开门见山，不绕弯子。
格式：**结论：** ...

## 第二步：关键数据表格
用 Markdown 表格列出影响比赛走向的关键数据指标。
必须包含以下维度（根据可用数据取舍）：

| 数据维度 | 主队 | 客队 | 联赛平均 | 解读 |
|----------|------|------|----------|------|
| 场均进球 | x.xx | x.xx | x.xx | ... |
| 场均 xG | x.xx | x.xx | x.xx | ... |
| 防守 (场均失球) | x.xx | x.xx | x.xx | ... |
| ELO 评分 | xxxx | xxxx | 1500 | ... |
| 近5场状态 | W-D-L-W-W | L-W-D-L-W | - | ... |

## 第三步：深度分析（3 点）
按以下优先级选择三个维度进行深度拆解：
1. **双方近期攻防效率对比** — xG 趋势、进球分布、防守漏洞
2. **关键对位分析** — 战术对位决定比赛走向的位置
3. **定位球威胁评估** — 角球/任意球攻防效率

每点控制在 150 字以内，数据引用必须标注来源和时间段。

---

# 数据引用规范

所有数据结论**必须**注明：
- **数据来源**（如 "ELO 数据库"、"API-Football"、"知识库"、"football-data.org"）
- **时间范围**（如 "2024-25 赛季至今"、"近 5 场比赛"、"近 10 次交锋"）

示例：
> "阿森纳近 5 场场均 xG 为 1.82，高于联赛平均 1.40（数据来源：API-Football 技术统计，2024-25 赛季）"

如果数据为模拟/估算，必须明确标注：
> "该数据为 ELO 估算值，非实时统计。配置 API Key 可获取精确数据。"

---

# 思维链要求

在给出最终判断前，在内心完成以下分析（不输出思考过程，但必须在回答中体现）：

1. **攻防效率分析**: 比较两队近 5-10 场的 xG/xGA 趋势，识别进攻火力上升/下降的球队
2. **关键对位识别**: 找出场上最具决定性的 2-3 组对位（如 "客队右边锋 vs 主队左后卫"）
3. **定位球威胁**: 评估两队在定位球进攻/防守上的相对优劣势
4. **综合判断**: 综合以上三点，结合 ELO 和泊松模型的数学预测，形成最终判断

---

# 推荐工作流程

当用户要求分析/预测一场比赛时，建议按以下顺序调用工具：

1. `search_knowledge_base` — 如果涉及战术概念，先查知识库
2. `get_team_statistics` × 2 — 获取主客两队真实赛季数据
3. `predict_match` — 输入获取到的数据，运行数学预测
4. `get_standings` — 查看联赛排名背景
5. `analyze_head_to_head` — 查历史交锋
6. 综合所有数据，按三段式格式输出分析

---

# 约束

- 用中文回答
- 不编造数据。没有数据时明确说"暂无数据"
- 足球比赛存在不确定性，所有预测仅供参考
- 保持客观专业，不因球队知名度而产生偏见
- 知识库内容优先用于解释战术概念，实时数据用于判断当前状态
"""


# ============================================================
# 动态上下文注入
# ============================================================

_CONTEXT_DETECT_KEYWORDS = [
    "预测", "分析", "vs", "VS", "对", "vs.", "对阵",
    "比赛", "赛前", "前瞻", "谁会赢", "怎么看",
    "predict", "analyze", "match", "preview",
]


def _should_inject_context(user_message: str) -> bool:
    """检测用户消息是否需要注入动态上下文"""
    msg = user_message.lower()
    return any(kw in msg for kw in _CONTEXT_DETECT_KEYWORDS)


async def _inject_match_context(
    messages: list[dict],
    user_message: str,
) -> list[dict]:
    """在用户消息前注入 <current_data> 动态上下文

    如果用户询问特定比赛的分析/预测，自动拉取相关数据
    并注入到消息中，形成增强版 Prompt。
    """
    try:
        from src.agent.context_builder import build_match_context

        # 使用简易启发式检测输入的球队名
        # 格式: TeamA vs TeamB, TeamA 对 TeamB, 等
        import re

        patterns = [
            r"(.+?)\s+vs\.?\s+(.+?)(?:\s|$|，|。|？)",
            r"(.+?)\s+对\s+(.+?)(?:\s|$|，|。|？)",
            r"(.+?)\s+对阵\s+(.+?)(?:\s|$|，|。|？)",
        ]

        home_team = away_team = None
        for pat in patterns:
            m = re.search(pat, user_message, re.IGNORECASE)
            if m:
                home_team = m.group(1).strip()
                away_team = m.group(2).strip()
                break

        if home_team and away_team:
            context_xml = await build_match_context(home_team, away_team)
            # 在用户消息前插入上下文
            return [{"role": "user", "content": context_xml}] + messages
    except Exception:
        pass

    return messages


# ============================================================
# Agent 类
# ============================================================

class FootballAgent:
    """足球分析智能体

    使用 Anthropic API 的 Function Calling 能力
    自动选择和执行工具, 综合生成分析结果
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.client = anthropic.Anthropic(
            api_key=api_key or config.ANTHROPIC_API_KEY
        )
        self.model = model or config.ANTHROPIC_MODEL
        self.tools = TOOLS_SCHEMA
        self.conversation_history: list[dict] = []

    async def chat(self, user_message: str) -> str:
        """处理用户消息, 返回 AI 分析结果

        Args:
            user_message: 用户输入的问题/指令

        Returns:
            AI 分析结果 (Markdown 格式)
        """
        messages: list[dict] = [
            {"role": "user", "content": user_message}
        ]

        # 如果有历史对话, 加入上下文
        if self.conversation_history:
            messages = self.conversation_history + messages

        # ---- 动态上下文注入 ----
        # 检测是否为比赛分析类查询，自动拉取实时数据
        if _should_inject_context(user_message):
            try:
                messages = await _inject_match_context(messages, user_message)
                logger.info("已注入动态上下文 (<current_data>)")
            except Exception as e:
                logger.warning(f"上下文注入失败 (非致命): {e}")

        logger.info(f"用户: {user_message[:100]}...")

        # ---- Anthropic API 调用循环 (支持多轮 Tool Use) ----
        max_turns = 6
        for turn in range(max_turns):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=3072,
                system=SYSTEM_PROMPT,
                tools=self.tools,
                messages=messages,
            )

            # 检查是否有 tool_use
            tool_uses = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            if not tool_uses:
                answer = response.content[0].text
                self._save_history(messages, answer)
                logger.info(f"AI 回复: {answer[:100]}...")
                return answer

            # 处理工具调用
            logger.info(f"第 {turn + 1} 轮工具调用: {[t.name for t in tool_uses]}")

            # 添加 assistant 消息
            messages.append({
                "role": "assistant",
                "content": [block.to_dict() for block in response.content],
            })

            # 执行工具并收集结果
            tool_results: list[dict] = []
            for tool_block in tool_uses:
                tool_name = tool_block.name
                tool_input = tool_block.input
                tool_id = tool_block.id

                logger.info(f"  执行: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

                result = await self._execute_tool(tool_name, tool_input)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result, ensure_ascii=False, indent=2),
                })

            # 添加工具结果到消息
            messages.append({
                "role": "user",
                "content": tool_results,
            })

        # 超过最大轮次, 强制总结
        logger.warning("达到最大工具调用轮次, 请求总结")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages + [{
                "role": "user",
                "content": "请根据以上所有数据，遵循三段式结构（结论→数据表→三点分析），用中文给出综合结论。",
            }],
        )
        return response.content[0].text

    async def _execute_tool(self, name: str, args: dict) -> Any:
        """执行工具函数"""
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": f"未知工具: {name}"}
        try:
            result = await handler(**args)
            return result
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}")
            return {"error": str(e)}

    def _save_history(self, messages: list[dict], answer: str) -> None:
        """保存对话历史 (保留最近 6 轮)"""
        self.conversation_history.append({
            "role": "user",
            "content": messages[0]["content"],
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": answer,
        })
        # 只保留最近 6 轮 (12 条消息)
        if len(self.conversation_history) > 12:
            self.conversation_history = self.conversation_history[-12:]

    def clear_history(self) -> None:
        """清空对话历史"""
        self.conversation_history = []


# ============================================================
# 便捷函数
# ============================================================

async def predict_match_simple(
    home_team: str,
    away_team: str,
    home_form: list[str] | None = None,
    away_form: list[str] | None = None,
) -> dict:
    """快速预测比赛 (不使用 Agent, 直接调用工具)"""
    return await predict_match(
        home_team=home_team,
        away_team=away_team,
        home_form=home_form,
        away_form=away_form,
    )
