# -*- coding: utf-8 -*-
"""
LLM Qualitative Analyst v3.1 (Phase 4)

DeepSeek-first (deepseek-harness, V4-Pro/V4-Flash), Anthropic fallback.
LLM provides qualitative context only — NEVER generates probabilities.
Model handles all quantitative work; LLM adds what the model cannot see.

Design:
- Evidence packet: structured match data (ELO, DC probs, market odds, league profile)
- Analyst prompt: "2-3 sentences of qualitative context. Do not suggest probabilities."
- Rate limiting: sequential, 0.3s delay between requests
- Cold starts skipped (no data to contextualize)
- Fallback: DeepSeek失败 → Anthropic → 预测正常运行(无注释)
"""
from __future__ import annotations

import json
import time
from typing import Any

LEAGUE_NAMES_CN = {
    "PL": "英超",
    "PD": "西甲",
    "BL1": "德甲",
    "SA": "意甲",
    "FL1": "法甲",
    # 非五大联赛 (体彩开盘, 分析为主)
    "ELC": "英冠", "BL2": "德乙", "FL2": "法乙",
    "DED": "荷甲", "DED2": "荷乙", "PPL": "葡超",
    "FIN": "芬超", "SWE": "瑞超", "NOR": "挪超", "NO1": "挪超",
    "J1": "日职", "KLEAGUE": "韩职", "BSA": "巴甲", "MLS": "美职", "SPL": "沙职",
    "UCL": "欧冠", "UEL": "欧联", "CLB": "解放者杯",
}


def build_evidence_packet(prediction: dict, intel_text: str = "") -> str:
    """Build a structured evidence packet for one match.

    intel_text: 用户提供的赛前情报 (伤停/首发/战意等), 追加到证据包末尾
    """
    home = prediction.get("home_team", "?")
    away = prediction.get("away_team", "?")
    league = prediction.get("league_code", "")
    league_name = LEAGUE_NAMES_CN.get(league, league)
    model = prediction.get("model", {})
    value = prediction.get("value") or {}
    bayes = prediction.get("bayesian") or {}
    elo_diff = prediction.get("elo_diff", 0)
    cold = prediction.get("cold_start", False)

    odds = prediction.get("odds") or {}
    odds_str = ""
    if odds:
        h = odds.get("home", 0)
        d = odds.get("draw", 0)
        a = odds.get("away", 0)
        if h and d and a:
            odds_str = f"赔率: {h:.2f}/{d:.2f}/{a:.2f}"

    lines = [
        f"=== {home} vs {away} ===",
        f"联赛: {league_name}",
        f"ELO: {prediction.get('elo_home', '?')} vs {prediction.get('elo_away', '?')} (差{elo_diff:+.0f})",
        f"模型概率: 主{model.get('home_win', 0):.1%} 平{model.get('draw', 0):.1%} 客{model.get('away_win', 0):.1%}",
    ]

    if odds_str:
        lines.append(odds_str)

    if bayes and "posterior" in bayes:
        post = bayes["posterior"]
        lines.append(f"贝叶斯后验: 主{post.get('home', 0):.1%} 平{post.get('draw', 0):.1%} 客{post.get('away', 0):.1%}")
        if "interpretation" in bayes:
            lines.append(f"市场融合: {bayes['interpretation']}")

    lines.extend([
        f"预期进球: {model.get('lambda_home', 0):.2f} - {model.get('lambda_away', 0):.2f}",
        f"大2.5: {model.get('over_25', 0):.1%} | BTTS: {model.get('btts', 0):.1%}",
    ])

    top5 = model.get("top_5_scores", [])
    if top5:
        scores_str = ", ".join(f"{s[0]}({s[1]:.1%})" for s in top5[:3])
        lines.append(f"最可能比分: {scores_str}")

    if value:
        edges = {
            "home": value.get("home_edge", 0) or 0,
            "draw": value.get("draw_edge", 0) or 0,
            "away": value.get("away_edge", 0) or 0,
        }
        edge_str = " ".join(f"{d}={edges[d]:+.1%}" for d in ["home", "draw", "away"])
        lines.append(f"Model-Market Edge: {edge_str}")
        edge_dir = value.get("best_direction", "none")
        if edge_dir != "none":
            lines.append(f"最强信号: {edge_dir} (Kelly {value.get('kelly', 0):.2%})")

    std = prediction.get("standings") or {}
    sh = std.get("home")
    sa = std.get("away")
    if sh or sa:
        parts = []
        if sh:
            zone = _zone_label(sh.get("pos"))
            z = f" ({zone})" if zone else ""
            parts.append(f"{home} #{sh.get('pos', '?')}{z} ({sh.get('points', '?')}分, 近况{sh.get('form', '?')})")
        if sa:
            zone = _zone_label(sa.get("pos"))
            z = f" ({zone})" if zone else ""
            parts.append(f"{away} #{sa.get('pos', '?')}{z} ({sa.get('points', '?')}分, 近况{sa.get('form', '?')})")
        lines.append("联赛积分榜: " + "; ".join(parts))

    # Phase 8: 赛程密度 + 近2季交锋
    sched = prediction.get("schedule") or {}
    if sched:
        lines.append(f"赛程密度: 主队7天{sched.get('home_7d', 0)}场 / 客队7天{sched.get('away_7d', 0)}场")
    h2h = prediction.get("h2h_recent")
    if h2h:
        lines.append(
            f"近2季交锋: 主队视角 {h2h.get('w', 0)}胜{h2h.get('d', 0)}平{h2h.get('l', 0)}负 "
            f"(总进球{h2h.get('gf', 0)}-{h2h.get('ga', 0)})"
        )

    # 市场视角: 让球盘 + 欧赔 + 波胆 + 半全场 + 大小球
    ah = prediction.get("ah_handicap")
    if ah:
        line_ = ah.get("goal_line")
        hc = ah.get("home_cover", 0)
        ac = ah.get("away_cover", 0)
        if line_ is not None:
            lines.append(f"亚盘(主{line_:+.1f}): 模型主覆盖{hc:.0%}/客覆盖{ac:.0%}")
    if prediction.get("odds"):
        o = prediction["odds"]
        if o.get("home") and o.get("draw") and o.get("away"):
            lines.append(f"欧赔: 主{o['home']:.2f}/平{o['draw']:.2f}/客{o['away']:.2f}")
    cs_v = prediction.get("cs_value") or []
    if cs_v:
        lines.append("波胆价值(模型vs市场): " + " · ".join(
            f"{v['score']} {v['model']:.1%}vs{v['market']:.1%}" for v in cs_v
        ))
    ou_v = prediction.get("ou_value")
    if ou_v:
        lines.append(f"大小球价值: {ou_v['side']} 模型{ou_v['model']:.0%} vs 市场{ou_v['market']:.0%}")
    htft = prediction.get("ht_ft_odds") or {}
    if htft:
        top_htft = sorted(htft.items(), key=lambda x: x[1])[:3]
        lines.append("半全场市场: " + " ".join(f"{k}@{v:.2f}" for k, v in top_htft))

    if cold:
        lines.append("[注意] 冷启动 — 球队参数来自联赛均值，不确定性高")

    if intel_text:
        lines.append("")
        lines.append("=== 赛前情报 (用户提供, 请重点参考) ===")
        lines.append(intel_text)

    return "\n".join(lines)


def _zone_label(pos) -> str | None:
    """积分榜分区 (战意/动机参考)"""
    if pos is None:
        return None
    if pos <= 3:
        return "争冠区"
    if pos <= 6:
        return "欧战区"
    if pos >= 15:
        return "保级区"
    return "中游"


def build_analyst_prompt(evidence: str) -> str:
    """Build the analyst prompt (八维评分框架, 参考 ajunai-football 开源框架改造)."""
    return f"""你是资深足球赛前分析师。以下是统计模型对一场比赛的结构化预测。请按八维框架做定性评估并输出方向分:

1. 市场视角: 亚盘/欧赔/大小球反映资金流向; 模型与市场分歧大时警惕模型盲区
2. 状态与攻防: 模型概率/预期进球/ELO差 反映实力与近期状态
3. 阵容与伤停: 必须区分核心主力与替补; 情报未提及伤停时明确说明, 不得编造
4. 交锋与克制: 仅参考"近2季交锋", 更早交锋易误导
5. 赛程与体能: 7天场次密度、双线作战、轮换概率
6. 天气与场地: 情报含天气才评; 没有就写"情报未提及, 权重记0"
7. 裁判: 情报含裁判任命才评; 未公布写"裁判未公布, 权重记0", 不猜测
8. 战意与轮换: 结合积分榜分区 (争冠/欧战/保级/中游), 不滥用"必须赢"

默认权重 (合计100%, 方向分 = Σ优势分×权重÷100):
市场20 / 状态攻防18 / 阵容伤停14 / 交锋克制8 / 赛程体能12 / 天气6 / 裁判6 / 战意轮换16
裁判未公布或天气无情报时, 把对应权重重新分配给维度1/2/5/8, 并在关键维度里注明。

硬校准规则:
- 你的结论方向必须与最可能比分方向一致
- 情报不足就明确写"数据不足已降权", 禁止编造伤停/天气/裁判/数字
- 概率数字只用证据中给出的, 不自己造

输出格式 (纯中文, 共6行, 不要概率数字, 不要投注建议):
方向分: (按权重计算, -5 至 +5, 正值利主队)
结论: (1句, 最可能方向+核心理由)
关键维度: (最强的2-3个维度, 各半句, 注明权重调整)
三条路径: (常规/平局/冷门 各半句带触发条件, 冷门路径必须基于可验证的反击/定位球/门将等真实条件)
反向验证: (1句: 如果这场预测错了, 最可能错在哪里)
触发器: (1句: 赛前什么变化会推翻结论, 如首发/伤停/天气)

{evidence}

分析师输出:"""


def query_analyst(
    evidence: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str | None:
    """Qualitative analyst: DeepSeek first (harness), Anthropic fallback."""
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
        from config import ANTHROPIC_API_KEY as ANTHRO_KEY
    except Exception:
        DEEPSEEK_API_KEY, DEEPSEEK_MODEL, ANTHRO_KEY = "", "deepseek-v4-pro", ""

    prompt = build_analyst_prompt(evidence)

    # 1) DeepSeek（deepseek-harness，关闭thinking）
    ds_key = api_key or DEEPSEEK_API_KEY
    if ds_key:
        result = _try_deepseek(prompt, ds_key, model or DEEPSEEK_MODEL)
        if result:
            return result
        print("  [警告] DeepSeek 失败，回退 Anthropic...")

    # 2) Anthropic（旧版回退）
    if not ANTHRO_KEY:
        return "[LLM不可用: 未配置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY]"

    a_model = model or "claude-haiku-4-5-20251001"
    result = _try_sdk(prompt, ANTHRO_KEY, a_model)
    if result is None:
        result = _try_http(prompt, ANTHRO_KEY, a_model)
    return result


def _try_deepseek(prompt: str, api_key: str, model: str) -> str | None:
    """Call DeepSeek via deepseek-harness (OpenAI-compatible, cost-optimized)."""
    try:
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=api_key, disable_thinking_by_default=True)
        resp = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": "你是资深足球赛前分析师。按用户要求的5行格式输出中文分析。不输出概率、不推荐投注、不编造。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        msg = resp.get("message") or {}
        text = msg.get("content") or ""
        return text.strip() if text else None
    except Exception as e:
        print(f"  [警告] DeepSeek harness 失败: {e}")
        return None


def _try_sdk(prompt: str, api_key: str, model: str) -> str | None:
    """Try using the anthropic Python SDK."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=200,
            temperature=0.7,
            system="你是资深足球分析师。只输出2-3句中文定性评估。不输出概率、不推荐投注。",
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
        return text.strip() if text else None
    except Exception as e:
        print(f"  [警告] Anthropic SDK 失败: {e}")
        return None


def _try_http(prompt: str, api_key: str, model: str) -> str | None:
    """Fallback: direct HTTP request to Anthropic API."""
    try:
        import urllib.request

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = json.dumps({
            "model": model,
            "max_tokens": 200,
            "temperature": 0.7,
            "system": "你是资深足球分析师。只输出2-3句中文定性评估。不输出概率、不推荐投注。",
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["content"][0]["text"]
            return text.strip() if text else None
    except Exception as e:
        print(f"  [警告] Anthropic HTTP 失败: {e}")
        return None


def audit_analysis(evidence: str, note: str, prior_note: str = "") -> str | None:
    """终盘独立自检 (参考 ajunai-football 开源框架的独立审计环节).

    审计项: 结论与概率/比分方向一致 / 未编造伤停天气裁判数字 / 维度间无矛盾 / 与早午盘存档变化有依据
    """
    prompt = (f"你是足球赛前报告独立审计员。请审计以下分析 (不要因为是你或同类模型生成就默认正确):\n\n"
              f"证据包:\n{evidence}\n\n分析结论:\n{note}\n")
    if prior_note:
        prompt += f"\n早盘/午盘存档 (对比结论变化是否有依据):\n{prior_note}\n"
    prompt += ("\n审计项: ① 结论方向与最可能比分/概率方向是否一致 ② 是否编造了证据里没有的伤停/天气/裁判/数字 "
               "③ 维度结论之间是否矛盾 ④ 与早午盘存档相比结论变化是否有依据。\n\n"
               "输出 (纯中文, 1行):\n自检: 通过 (1句说明) 或 自检: 发现P1/P2问题 (具体是什么, 1句)")
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=DEEPSEEK_API_KEY, disable_thinking_by_default=True)
        resp = client.chat(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是足球报告独立审计员。只输出一行: 自检: 通过(...) 或 自检: 发现P1/P2(...)。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=140,
            temperature=0.3,
        )
        msg = resp.get("message") or {}
        text = (msg.get("content") or "").strip()
        return text if text else None
    except Exception as e:
        print(f"  [自检] 失败: {e}")
        return None


def batch_analyze(
    predictions: list[dict],
    api_key: str | None = None,
    model: str | None = None,
    delay: float = 0.3,
    intel_text: str = "",
    prior_notes: dict[str, str] | None = None,
) -> dict[str, str]:
    """Run qualitative analysis on all predictions.

    prior_notes: 早盘/午盘七维分析存档 (key=场次名), 终盘时注入供追溯对比
    """
    notes: dict[str, str] = {}
    prior_notes = prior_notes or {}

    for i, pred in enumerate(predictions):
        home = pred.get("home_team", "?")
        away = pred.get("away_team", "?")
        match_key = f"{home} vs {away}"

        # 冷启动但有市场赔率 → 仍做七维分析 (市场视角是第一维度, 非五大联赛场次也靠它);
        # 完全无赔率的冷启动 → 跳过 (无任何可分析证据)
        odds_now = pred.get("odds") or {}
        if pred.get("cold_start") and not odds_now.get("home"):
            notes[match_key] = "[无赔率且冷启动 — 跳过LLM分析]"
            print(f"  [{i+1}/{len(predictions)}] {match_key}: 跳过（冷启动且无赔率）")
            continue
        if pred.get("cold_start"):
            print(f"  [{i+1}/{len(predictions)}] {match_key}: 冷启动(市场定价为主), 仍做八维分析")

        evidence = build_evidence_packet(pred, intel_text=intel_text)
        if prior_notes.get(match_key):
            evidence += ("\n\n=== 早盘/午盘七维分析存档 (请对照: 注意赔率与信息自存档以来的变化) ===\n"
                         + prior_notes[match_key])
        print(f"  [{i+1}/{len(predictions)}] {match_key}: 分析中...")

        note = query_analyst(evidence, api_key, model)
        if note:
            notes[match_key] = note
            preview = note[:60] + "..." if len(note) > 60 else note
            print(f"    -> {preview}")
        else:
            notes[match_key] = "[LLM分析失败]"
            print(f"    -> FAILED")

        if i < len(predictions) - 1:
            time.sleep(delay)

    return notes
