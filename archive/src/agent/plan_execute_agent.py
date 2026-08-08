"""
Plan-and-Execute Agent —— 四阶段自主规划执行流水线

架构:
  Phase 1: UNDERSTAND & PLAN   → Claude 提取意图 + 生成 JSON 执行计划
  Phase 2: EXECUTE             → 拓扑排序执行, 独立步骤并行
  Phase 3: SYNTHESIZE          → Chain-of-Thought 汇总推理
  Phase 4: VALIDATE & REFINE   → 数据矛盾自检, 自动回查修正

不依赖 LangChain, 纯 Anthropic API + asyncio 实现
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
from loguru import logger

from src.agent.tools import (
    analyze_head_to_head,
    backtest_match,
    calculate_recent_xg,
    compare_model_vs_market,
    get_live_scores,
    get_match_odds,
    get_standings,
    get_team_info,
    get_team_statistics,
    predict_match,
    review_yesterday_matches,
    search_knowledge_base,
    search_matches,
)
from src.utils.config import config

# generate_radar_chart 需要 matplotlib，作为可选工具
# 如果无法导入，运行时调用会返回错误提示而非崩溃
try:
    from src.agent.tools import generate_radar_chart  # noqa: F811
except ImportError:
    async def generate_radar_chart(**kwargs):  # type: ignore[no-redef]
        return {"error": "请安装 matplotlib: pip install matplotlib"}

# ============================================================
# 工具注册表 (name → handler)
# ============================================================

TOOL_REGISTRY: dict[str, Any] = {
    "search_matches":          search_matches,
    "get_live_scores":         get_live_scores,
    "get_team_statistics":     get_team_statistics,
    "get_team_info":           get_team_info,
    "get_standings":           get_standings,
    "predict_match":           predict_match,
    "analyze_head_to_head":    analyze_head_to_head,
    "calculate_recent_xg":     calculate_recent_xg,
    "search_knowledge_base":   search_knowledge_base,
    "generate_radar_chart":    generate_radar_chart,
    "get_match_odds":            get_match_odds,
    "compare_model_vs_market":   compare_model_vs_market,
    "review_yesterday_matches":  review_yesterday_matches,
    "backtest_match":            backtest_match,
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PlanStep:
    """执行计划中的一步"""
    id: str                                # e.g. "step_1"
    tool: str                              # 工具名
    args: dict = field(default_factory=dict)
    description: str = ""                  # 人类可读描述
    depends_on: list[str] = field(default_factory=list)  # 前置步骤 ID
    parallel: bool = False                 # 是否可与其他步骤并行

    # 运行时填充
    status: str = "pending"                # pending | running | done | failed
    result: Any = None
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class ExecutionPlan:
    """完整执行计划"""
    user_intent: str = ""                  # 用户意图摘要
    entities: dict = field(default_factory=dict)  # {teams: [], league: "", date: ""}
    steps: list[PlanStep] = field(default_factory=list)
    estimated_tools: int = 0


@dataclass
class PhaseResult:
    """单阶段执行结果"""
    phase: str
    success: bool
    data: Any = None
    error: str = ""
    elapsed_ms: float = 0.0


# ============================================================
# Prompt 模板
# ============================================================

PLANNER_SYSTEM_PROMPT = """你是一名资深足球分析任务规划器。你的唯一任务是: 根据用户问题, 生成一个结构化的 JSON 执行计划。

## 可用工具

| 工具名 | 功能 | 关键参数 |
|--------|------|----------|
| `search_knowledge_base` | 搜索战术知识库 | query (自然语言) |
| `get_live_scores` | 获取实时比分 | league, team |
| `search_matches` | 搜索赛程 | competition, matchday, date |
| `get_team_statistics` | 球队赛季统计数据 | team_name, competition |
| `get_team_info` | 球队基本信息+ELO | team_name |
| `get_standings` | 联赛积分榜 | competition |
| `predict_match` | 泊松+ELO预测 | home_team, away_team, ... |
| `calculate_recent_xg` | 近N场xG分析 | team_name, matches |
| `analyze_head_to_head` | 历史交锋 | team_a, team_b |
| `generate_radar_chart` | 能力雷达图 | team_name, compare_with |
| `get_match_odds` | 赔率数据 (欧赔+必发) | home_team, away_team |
| `compare_model_vs_market` | 模型 vs 市场价值对比 | home_team, away_team |
| `review_yesterday_matches` | 复盘昨日比赛 & 偏差分析 | league |
| `backtest_match` | 单场回测 (输入真实比分) | home_team, away_team, home_goals, away_goals |

## 计划生成规则

1. **依赖关系**: 如果步骤 B 需要步骤 A 的结果作为参数, 标记 depends_on
2. **并行优化**: 互不依赖的步骤标记 parallel: true (如同时查两队统计)
3. **先知识后数据**: 涉及战术概念先 search_knowledge_base
4. **先数据后预测**: predict_match 应在 get_team_statistics 之后
5. **赔率对比**: compare_model_vs_market 应在 predict_match 之后调用, 用于交叉验证
6. **最少步骤**: 只规划必要的步骤, 不要过度调用工具

## 输出格式

严格输出以下 JSON (不要包含 ```json``` 标记, 不要有额外文字):

{
  "user_intent": "一句话总结用户意图",
  "entities": {
    "teams": ["球队1", "球队2"],
    "league": "联赛名",
    "date": "日期或null"
  },
  "steps": [
    {
      "id": "step_1",
      "tool": "工具名",
      "args": {"参数名": "值"},
      "description": "这一步做什么",
      "depends_on": [],
      "parallel": false
    }
  ],
  "estimated_tools": 3
}"""


SYNTHESIZER_SYSTEM_PROMPT = """你是一名持有 UEFA Pro 执照的足球分析师。

你的任务: 基于以下工具执行结果, 生成一份专业分析报告。

## 报告结构 (三段式)

### 第一步: 结论先行
用 2-3 句话给出核心判断。格式: **结论:** ...

### 第二步: 关键数据表
Markdown 表格列出关键指标对比:

| 维度 | 主队 | 客队 | 解读 |
|------|------|------|------|

### 第三步: 深度分析 (3点)
1. **攻防效率** — xG 趋势、进球分布、防守漏洞
2. **关键对位** — 决定比赛走向的战术对位
3. **定位球威胁** — 角球/任意球攻防效率

## 规则
- 用中文
- 所有数据引用标注来源和时间段
- 知识库内容与实时数据相互印证
- 不编造数据, 没有数据时如实说明
- 足球比赛存在不确定性, 分析仅供参考

## Chain-of-Thought 要求
在最终回答前, 用 `<!-- 思考 -->` 注释形式完成以下推理 (不输出给用户):
1. 两队近期攻防效率对比结论
2. 最具决定性的关键对位
3. 定位球环节的强弱对比
4. 综合以上, 你认为比赛最可能的走向

以下是工具执行结果:"""


VALIDATOR_SYSTEM_PROMPT = """你是一名严谨的足球数据审核员。检查以下分析报告是否存在数据矛盾或逻辑错误。

## 检查清单
1. 报告中引用的数字是否与工具返回的原始数据一致？
2. 胜平负概率之和是否约等于 100%？
3. 预期进球与实际进球的关系判断是否正确？
4. 数据来源和时间段是否已标注？
5. 是否有前后矛盾的陈述（如"进攻强"和"场均进球低于平均"同时出现）？

## 输出格式

如果报告无误, 输出: {"valid": true, "issues": []}

如果发现问题, 输出:
{
  "valid": false,
  "issues": [
    {"severity": "high|medium|low", "description": "问题描述", "fix": "建议修正"}
  ],
  "need_recheck": true,
  "recheck_tools": ["需要重新调用的工具名"]
}

只输出 JSON, 不要包含其他文字。"""


# ============================================================
# Plan-and-Execute Agent
# ============================================================

class PlanExecuteAgent:
    """四阶段规划执行智能体"""

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self.client = anthropic.Anthropic(
            api_key=api_key or config.ANTHROPIC_API_KEY
        )
        self.model = model or config.ANTHROPIC_MODEL
        self.max_validate_rounds = 2
        self._execution_cache: dict[str, Any] = {}  # 步骤结果缓存

    # ================================================================
    # 主入口
    # ================================================================

    async def run(self, user_input: str) -> str:
        """运行完整的 Plan-and-Execute 流水线"""
        started = time.time()
        self._execution_cache = {}
        logger.info("=" * 50)
        logger.info(f"Plan-Execute 启动: {user_input[:80]}...")

        # ---- Phase 1: Understand & Plan ----
        plan = await self._phase1_plan(user_input)
        if not plan or not plan.steps:
            logger.warning("计划生成失败, 降级到标准 Tool Use 模式")
            return await self._fallback_chat(user_input)

        self._print_plan(plan)

        # ---- Phase 2: Execute ----
        await self._phase2_execute(plan)

        # ---- Phase 3: Synthesize ----
        report = await self._phase3_synthesize(user_input, plan)

        # ---- Phase 4: Validate & Refine ----
        final = await self._phase4_validate(plan, report)

        elapsed = time.time() - started
        logger.info(f"Plan-Execute 完成 ({elapsed:.1f}s)")

        return final

    # ================================================================
    # Phase 1: UNDERSTAND & PLAN
    # ================================================================

    async def _phase1_plan(self, user_input: str) -> ExecutionPlan | None:
        """Claude 分析意图并生成 JSON 执行计划"""
        print("\n" + "─" * 50)
        print("🧠 Phase 1: 分析意图 & 制定计划...")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=PLANNER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_input}],
            )
        except Exception as e:
            logger.error(f"Planner 调用失败: {e}")
            return None

        raw = response.content[0].text.strip()

        # 提取 JSON
        plan_data = self._extract_json(raw)
        if not plan_data:
            logger.error(f"无法从 Planner 响应中提取 JSON:\n{raw[:500]}")
            return None

        try:
            steps = [
                PlanStep(
                    id=s["id"],
                    tool=s["tool"],
                    args=s.get("args", {}),
                    description=s.get("description", ""),
                    depends_on=s.get("depends_on", []),
                    parallel=s.get("parallel", False),
                )
                for s in plan_data.get("steps", [])
            ]

            plan = ExecutionPlan(
                user_intent=plan_data.get("user_intent", ""),
                entities=plan_data.get("entities", {}),
                steps=steps,
                estimated_tools=plan_data.get("estimated_tools", len(steps)),
            )
            return plan
        except Exception as e:
            logger.error(f"计划解析失败: {e}")
            return None

    # ================================================================
    # Phase 2: EXECUTE
    # ================================================================

    async def _phase2_execute(self, plan: ExecutionPlan) -> None:
        """按拓扑序执行计划步骤, 独立步骤并行"""
        print("\n" + "─" * 50)
        print(f"⚡ Phase 2: 执行 {len(plan.steps)} 个步骤...")

        if not plan.steps:
            return

        # 构建依赖图, 分组执行
        remaining = {s.id: s for s in plan.steps}
        completed: set[str] = set()

        round_num = 0
        while remaining:
            round_num += 1
            # 找出所有依赖已满足的步骤
            ready = [
                s for s in remaining.values()
                if all(d in completed for d in s.depends_on)
            ]
            if not ready:
                # 死锁检测 —— 跳过无法满足依赖的步骤
                stuck = [f"{s.id}(depends={s.depends_on})" for s in remaining.values()]
                logger.error(f"执行死锁, 无法继续: {stuck}")
                break

            # 分离并行组和串行组
            parallel_steps = [s for s in ready if s.parallel]
            serial_steps = [s for s in ready if not s.parallel]

            # 并行组 → asyncio.gather
            if parallel_steps:
                tasks = [self._execute_step(s) for s in parallel_steps]
                await asyncio.gather(*tasks)

            # 串行组 → 逐个执行
            for s in serial_steps:
                if s.id not in completed:  # 可能已被并行组完成
                    await self._execute_step(s)

            # 更新完成集合
            for s in ready:
                completed.add(s.id)
                del remaining[s.id]

        # 汇总
        ok = sum(1 for s in plan.steps if s.status == "done")
        fail = sum(1 for s in plan.steps if s.status == "failed")
        print(f"   完成: {ok}/{len(plan.steps)} (失败: {fail})")

    async def _execute_step(self, step: PlanStep) -> None:
        """执行单个步骤并缓存结果"""
        step.status = "running"
        t0 = time.time()

        # 注入依赖步骤的结果到 args
        resolved_args = dict(step.args)
        for dep_id in step.depends_on:
            dep_result = self._execution_cache.get(dep_id)
            if dep_result and isinstance(dep_result, dict):
                # 自动注入常用结果字段
                if "team_name" not in resolved_args and "name" in dep_result:
                    resolved_args.setdefault("team_name", dep_result.get("name"))
                if "team_a" not in resolved_args and "team_a" in dep_result:
                    resolved_args.setdefault("team_a", dep_result.get("team_a"))

        handler = TOOL_REGISTRY.get(step.tool)
        if handler is None:
            step.status = "failed"
            step.error = f"未知工具: {step.tool}"
            return

        try:
            result = await handler(**resolved_args)
            step.result = result
            step.status = "done"
            step.elapsed_ms = (time.time() - t0) * 1000
            self._execution_cache[step.id] = result

            # 进度打印
            summary = str(result)[:80].replace("\n", " ")
            if isinstance(result, dict):
                summary = result.get("summary", result.get("message", summary))
            status_icon = "✅" if step.status == "done" else "❌"
            print(f"   {status_icon} {step.id}: {step.description} ({step.elapsed_ms:.0f}ms)")
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.elapsed_ms = (time.time() - t0) * 1000
            self._execution_cache[step.id] = {"error": str(e)}
            print(f"   ❌ {step.id}: {step.description} — {e}")

    # ================================================================
    # Phase 3: SYNTHESIZE
    # ================================================================

    async def _phase3_synthesize(self, user_input: str, plan: ExecutionPlan) -> str:
        """将所有工具结果汇总, Chain-of-Thought 推理生成报告"""
        print("\n" + "─" * 50)
        print("📝 Phase 3: 综合推理 & 生成报告...")

        # 构建工具结果摘要
        results_block = self._format_execution_results(plan)

        prompt = f"""## 用户原始问题
{user_input}

## 执行计划
{json.dumps({"intent": plan.user_intent, "entities": plan.entities}, ensure_ascii=False, indent=2)}

## 工具执行结果
{results_block}

---

请基于以上所有数据，按三段式结构（结论→数据表→三点分析）生成分析报告。
在报告前用 <!-- 思考 --> 注释完成 Chain-of-Thought 推理。"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=3072,
            system=SYNTHESIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # ================================================================
    # Phase 4: VALIDATE & REFINE
    # ================================================================

    async def _phase4_validate(self, plan: ExecutionPlan, report: str) -> str:
        """自检报告数据一致性, 发现矛盾自动回查修正"""
        print("\n" + "─" * 50)
        print("🔍 Phase 4: 数据校验...")

        current_report = report

        for rnd in range(self.max_validate_rounds):
            prompt = f"""## 原始工具数据
{self._format_execution_results(plan)}

## 分析报告
{current_report}

请逐项检查报告是否有数据矛盾或逻辑错误。"""

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=VALIDATOR_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e:
                logger.warning(f"Validator 调用失败: {e}")
                break

            raw = response.content[0].text.strip()
            verdict = self._extract_json(raw)

            if not verdict:
                print("   ⚠️ Validator 返回格式异常, 跳过校验")
                break

            if verdict.get("valid"):
                print("   ✅ 数据一致性校验通过")
                break

            issues = verdict.get("issues", [])
            high_issues = [i for i in issues if i.get("severity") == "high"]

            print(f"   ⚠️ 发现 {len(issues)} 个问题 (高严重: {len(high_issues)})")
            for issue in issues:
                print(f"      [{issue.get('severity', '?')}] {issue.get('description', '')[:100]}")

            if not verdict.get("need_recheck") or not high_issues:
                # 低严重性问题, 不重新执行
                break

            # 重新执行指定工具
            recheck_tools = verdict.get("recheck_tools", [])
            if recheck_tools and rnd < self.max_validate_rounds - 1:
                print(f"   🔄 重新执行: {recheck_tools}")
                for step in plan.steps:
                    if step.tool in recheck_tools:
                        step.status = "pending"
                        await self._execute_step(step)

                # 重新生成报告 (递归调用 Phase 3)
                current_report = await self._phase3_synthesize(
                    f"数据校验发现问题后重新分析 (第{rnd + 1}轮修正)",
                    plan,
                )
            else:
                break

        return current_report

    # ================================================================
    # 辅助方法
    # ================================================================

    def _format_execution_results(self, plan: ExecutionPlan) -> str:
        """将所有步骤结果格式化为结构化文本"""
        parts = []
        for s in plan.steps:
            status = "✅" if s.status == "done" else "❌"
            parts.append(f"\n### {status} {s.id}: {s.description}")
            parts.append(f"工具: {s.tool} | 参数: {json.dumps(s.args, ensure_ascii=False)}")
            if s.status == "done" and s.result is not None:
                result_str = json.dumps(s.result, ensure_ascii=False, indent=2)
                # 截断过长结果
                if len(result_str) > 2000:
                    result_str = result_str[:2000] + "\n... (结果已截断)"
                parts.append(f"结果:\n```json\n{result_str}\n```")
            elif s.status == "failed":
                parts.append(f"错误: {s.error}")
            else:
                parts.append("状态: 未执行")
        return "\n".join(parts)

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从文本中提取 JSON 对象 (兼容 Claude 的各种输出格式)"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试匹配最外层 {...}
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _print_plan(self, plan: ExecutionPlan) -> None:
        """打印执行计划"""
        print(f"\n   意图: {plan.user_intent}")
        print(f"   实体: {json.dumps(plan.entities, ensure_ascii=False)}")
        print(f"   步骤:")
        for s in plan.steps:
            deps = f" ← {', '.join(s.depends_on)}" if s.depends_on else ""
            parallel_mark = " ⚡并行" if s.parallel else ""
            print(f"      {s.id}: {s.description} ({s.tool}){deps}{parallel_mark}")

    # ---- 降级 ----

    async def _fallback_chat(self, user_input: str) -> str:
        """Plan 失败时降级为普通 Tool Use 模式"""
        import anthropic as _anthropic
        from src.agent.tool_schemas import TOOLS_SCHEMA
        from src.agent.football_agent import SYSTEM_PROMPT

        messages = [{"role": "user", "content": user_input}]
        for _ in range(5):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS_SCHEMA,
                messages=messages,
            )
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return response.content[0].text
            messages.append({"role": "assistant", "content": [b.to_dict() for b in response.content]})
            results = []
            for tb in tool_uses:
                handler = TOOL_REGISTRY.get(tb.name)
                r = await handler(**tb.input) if handler else {"error": f"未知工具: {tb.name}"}
                results.append({"type": "tool_result", "tool_use_id": tb.id,
                                "content": json.dumps(r, ensure_ascii=False, indent=2)})
            messages.append({"role": "user", "content": results})
        return "抱歉，分析过程超时。请简化问题后重试。"
