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

    if cold:
        lines.append("[注意] 冷启动 — 球队参数来自联赛均值，不确定性高")

    if intel_text:
        lines.append("")
        lines.append("=== 赛前情报 (用户提供, 请重点参考) ===")
        lines.append(intel_text)


    return "\n".join(lines)


def build_analyst_prompt(evidence: str) -> str:
    """Build the Claude prompt for qualitative analysis."""
    return f"""你是资深足球分析师。以下是统计模型对一场比赛的结构化预测。模型无法看到以下因素：伤病、战意、赛程密集度、杯赛重要性、战术匹配度、天气等。

请用2-3句中文提供定性评估。你可以：
- 指出模型可能高估或低估主队的原因（例如：客队轮换主力、主队杯赛分心）
- 提及联赛风格倾向（例如：法甲低进球率、德甲大球倾向）
- 标注关键不确定性（例如：揭幕战、新帅首秀、德比战心理因素）

严格要求：
- 不要输出概率数字
- 不要建议投注金额
- 简洁，2-3句即可
- 纯中文

{evidence}

分析师注释（2-3句中文）:"""


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
                {"role": "system", "content": "你是资深足球分析师。只输出2-3句中文定性评估。不输出概率、不推荐投注。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
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


def batch_analyze(
    predictions: list[dict],
    api_key: str | None = None,
    model: str | None = None,
    delay: float = 0.3,
    intel_text: str = "",
) -> dict[str, str]:
    """Run qualitative analysis on all predictions."""
    notes: dict[str, str] = {}

    for i, pred in enumerate(predictions):
        home = pred.get("home_team", "?")
        away = pred.get("away_team", "?")
        match_key = f"{home} vs {away}"

        if pred.get("cold_start"):
            notes[match_key] = "[冷启动 — 跳过LLM分析]"
            print(f"  [{i+1}/{len(predictions)}] {match_key}: 跳过（冷启动）")
            continue

        evidence = build_evidence_packet(pred, intel_text=intel_text)
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
