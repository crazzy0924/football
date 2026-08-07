#!/usr/bin/env python3
"""
足球预测管线 v2.0
架构: 数据层(Python) → 推理层(LLM) → 审核层(LLM) → 规则引擎 → JSON输出

精华:
  ✅ LLM-in-the-loop — 推理和审核交给模型, 代码只做数据+规则
  ✅ Reflexion Pattern — Actor预测 + Reviewer校验
  ✅ 规则引擎 — 深盘/联赛风格/数据不足, 硬约束兜底
  ✅ 结构化输出 — 纯JSON, 不手写HTML

用法:
  python run_pipeline.py              # 完整预测
  python run_pipeline.py --matches 5  # 只看5场
  python run_pipeline.py --review     # 复盘昨天
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 修复 Windows GBK 编码下 emoji 打印问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── 项目根目录 ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── 数据层 (Python处理) ─────────────────────────────────
from src.models.elo import EloSystem
from src.models.league_profiles import LEAGUE_PROFILES, LeagueProfile, get_profile
from src.models.dixon_coles import dc_marginals
from src.models.baseline import baseline_predict
from src.models.best_bets import recommend_bets
from src.models.cold_start import ColdStartEngine
from src.models.odds_analyzer import calculate_implied_probability
from src.data.team_registry import resolve_team

# ── 日志 ───────────────────────────────────────────────
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")


# ══════════════════════════════════════════════════════════════
# 联赛映射 (严格匹配, 不过度泛化)
# ══════════════════════════════════════════════════════════════

LEAGUE_MAP: list[tuple[str, str]] = [
    # 格式: (Kambi联赛名关键词, 我们的代码)
    ("England - Premier League", "PL"),
    ("England - Championship", "ELC"),
    ("England - EFL Cup", "ELC"),
    ("England - League One", "ELC"),
    ("England - League Two", "ELC"),
    ("Spain - La Liga", "PD"),
    ("Germany - Bundesliga", "BL1"),
    ("Germany - 2. Bundesliga", "BL2"),
    ("Italy - Serie A", "SA"),
    ("France - Ligue 1", "FL1"),
    ("France - Ligue 2", "FL1"),
    ("Netherlands - Eredivisie", "DED"),
    ("Portugal - Liga Portugal", "PPL"),
    ("Scotland - Championship", "SCO"),
    ("Scotland - Premiership", "SCO"),
    ("UEFA Champions League", "CL"),
    ("UEFA Europa League", "EL"),
    ("UEFA Europa Conference League", "CLQ"),
    ("Major League Soccer", "MLS"),
    ("Leagues Cup", "LC"),
    ("Liga MX", "LIGA_MX"),
    ("Brazil", "BSA"),
    ("J1 League", "J1"),
    ("China Super League", "CSL"),
    ("K League", "KLEAGUE"),
    ("Austria - Bundesliga", "AUT"),
    ("Belgium - First Division A", "BEL"),
    ("Denmark - Superligaen", "DEN"),
    ("Norway - Eliteserien", "NOR"),
    ("Sweden", "SWE"),
    ("Poland - Ekstraklasa", "POL"),
    ("Czechia - 1. Liga", "CZE"),
    ("Switzerland - Super League", "SWI"),
    ("Romania - Superliga", "ROM"),
    ("Bulgaria - Parva Liga", "BUL"),
    ("Hungary - NB I", "HUN"),
    ("International Clubs - Club Friendly", "FRIENDLY"),
]


def map_league(kambi_name: str) -> tuple[str, LeagueProfile]:
    """联赛名 → (代码, 画像)"""
    name = kambi_name.strip()
    for keyword, code in LEAGUE_MAP:
        if keyword.lower() in name.lower():
            return code, get_profile(code)
    # 资格赛兜底
    if "qualif" in name.lower():
        return "CLQ", get_profile("CLQ")
    return "OTHER", get_profile("OTHER")


# ══════════════════════════════════════════════════════════════
# 阶段1: 数据层 — Python采集+整理
# ══════════════════════════════════════════════════════════════

def fetch_kambi_data() -> list[dict]:
    """拉取今日所有足球比赛的Kambi赔率"""
    import requests

    env_path = ROOT / ".env"
    KEY = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ODDS_API_IO_KEY="):
                KEY = line.split("=", 1)[1].strip()
                break
    if not KEY:
        logger.error("未找到 ODDS_API_IO_KEY")
        return []

    BOOKMAKER = "Unibet"

    # 拉取事件
    r = requests.get("https://api.odds-api.io/v3/events", params={
        "sport": "football", "bookmaker": BOOKMAKER, "apiKey": KEY,
    }, timeout=30)
    events = r.json()
    if isinstance(events, dict) and "error" in events:
        logger.error(f"API错误: {events['error']}")
        return []
    if not isinstance(events, list):
        logger.error(f"API返回格式异常: {type(events)}")
        return []

    pending = [e for e in events if e.get("status") in ("pending", "live")]
    logger.info(f"Kambi: {len(pending)} 场待踢 / 共 {len(events)} 场")

    # 只取重点联赛 (映射成功的)
    focus = []
    for e in pending:
        code, _ = map_league(e.get("league", {}).get("name", ""))
        if code != "OTHER":
            focus.append(e)

    # 最多30场 (API限流 + 精力聚焦)
    focus = focus[:30]
    logger.info(f"聚焦 {len(focus)} 场重点联赛比赛")

    # 拉取赔率
    for i, m in enumerate(focus):
        try:
            time.sleep(0.15)
            r2 = requests.get("https://api.odds-api.io/v3/odds", params={
                "eventId": m["id"], "bookmakers": BOOKMAKER, "apiKey": KEY,
            }, timeout=15)
            data = r2.json()
            bms = data.get("bookmakers", {})
            if isinstance(bms, dict):
                for _, markets in bms.items():
                    if isinstance(markets, list):
                        for mkt in markets:
                            if mkt.get("name") in ("ML", "1X2", "Full Time Result"):
                                odds_list = mkt.get("odds", [])
                                if odds_list:
                                    o = odds_list[0]
                                    m["odds_1x2"] = {
                                        "home": float(o.get("home", 0)),
                                        "draw": float(o.get("draw", 0)),
                                        "away": float(o.get("away", 0)),
                                    }
                                    m["odds_source"] = f"{BOOKMAKER} (Kambi)"
                                    break
        except Exception as e:
            logger.debug(f"  {m.get('home','')[:20]}: {e}")

    with_odds = sum(1 for m in focus if m.get("odds_1x2"))
    logger.info(f"有赔率: {with_odds}/{len(focus)}")

    # 缓存到本地
    out_path = ROOT / "data" / "kambi_odds.json"
    out_path.write_text(json.dumps(focus, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    return focus


def build_match_context(match: dict) -> dict[str, Any]:
    """为单场比赛构建LLM推理所需的结构化上下文

    这是阶段1的核心输出: 把所有数据打包成LLM能理解的格式。
    """
    home_name = match.get("home", "Unknown")
    away_name = match.get("away", "Unknown")
    league_name = match.get("league", {}).get("name", "")
    league_code, profile = map_league(league_name)
    odds_1x2 = match.get("odds_1x2", {})

    # ELO
    home_elo = EloSystem.get_elo(home_name)
    away_elo = EloSystem.get_elo(away_name)
    if home_elo == EloSystem.DEFAULT_ELO:
        home_elo = profile.elo_base
    if away_elo == EloSystem.DEFAULT_ELO:
        away_elo = profile.elo_base
    elo_diff = home_elo - away_elo

    # Shin去水
    market = None
    if odds_1x2:
        imp = calculate_implied_probability(
            odds_1x2["home"], odds_1x2["draw"], odds_1x2["away"], method="shin")
        market = {
            "home": imp.home, "draw": imp.draw, "away": imp.away,
            "margin": imp.margin,
            "raw_odds": odds_1x2,
        }

    # 联赛基线
    baseline = baseline_predict(home_name, away_name, league_code)

    # 泊松 λ (用于参考, LLM不用自己算)
    home_attack = 1.0 + (home_elo - profile.elo_base) / 400 * 0.6
    away_attack = 1.0 + (away_elo - profile.elo_base) / 400 * 0.6
    home_defense = 1.0 - (home_elo - profile.elo_base) / 400 * 0.5
    away_defense = 1.0 - (away_elo - profile.elo_base) / 400 * 0.5

    base = profile.avg_total_goals / 2
    lam_h = max(0.1, base * home_attack * away_defense * (1 + profile.home_goal_boost))
    lam_a = max(0.1, base * away_attack * home_defense)

    # Dixon-Coles
    dc = dc_marginals(lam_h, lam_a, max_g=8, rho=-0.10)

    # 深盘预检
    deep_warning = None
    if market and market["home"] > 0.78:
        if elo_diff > 200 and profile.over_25_rate < 0.55:
            deep_warning = "🔴 深盘+小球联赛: 禁止-2.0以上让球"
        else:
            deep_warning = "🟡 深盘: 自动降一档置信"

    return {
        # 基本信息
        "match": f"{home_name} vs {away_name}",
        "league": profile.name,
        "league_code": league_code,
        "kickoff": match.get("date", ""),
        "status": match.get("status", ""),

        # 联赛画像 (LLM推理的关键参考)
        "league_profile": {
            "name": profile.name,
            "avg_goals": profile.avg_total_goals,
            "home_win_rate": profile.home_win_rate,
            "draw_rate": profile.draw_rate,
            "over_25_rate": profile.over_25_rate,
            "btts_rate": profile.btts_rate,
            "style": profile.style,
            "notes": profile.notes,
        },

        # ELO
        "elo": {
            "home": round(home_elo, 0),
            "away": round(away_elo, 0),
            "diff": round(elo_diff, 0),
            "home_source": "ELO数据库" if EloSystem.get_elo(home_name) != EloSystem.DEFAULT_ELO else "联赛基准",
            "away_source": "ELO数据库" if EloSystem.get_elo(away_name) != EloSystem.DEFAULT_ELO else "联赛基准",
        },

        # 市场信号
        "market": market,

        # 数据参考 (给LLM参考, 不是最终决策)
        "data_reference": {
            "poisson_lambda": {"home": round(lam_h, 2), "away": round(lam_a, 2)},
            "dixon_coles": {
                "home_win": dc["home_win"], "draw": dc["draw"], "away_win": dc["away_win"],
                "over_25": dc["over_25"], "btts": dc["btts"],
                "top3_scores": [(s, round(p, 3)) for s, p in dc["top_5_scores"][:3]],
                "one_one_prob": dc["diagnostics"]["1-1_prob"],
                "zero_zero_prob": dc["diagnostics"]["0-0_prob"],
            },
            "baseline": {
                "home_win": baseline.home_win, "draw": baseline.draw,
                "away_win": baseline.away_win, "expected_goals": baseline.expected_total_goals,
            },
        },

        # 规则预检
        "rule_check": {
            "deep_handicap_warning": deep_warning,
            "data_quality": "⚠ 数据不足, 参考为主" if (home_elo == profile.elo_base and away_elo == profile.elo_base) else "数据充足",
        },
    }


# ══════════════════════════════════════════════════════════════
# 阶段2: 推理层 — LLM做预测 (Actor)
# ══════════════════════════════════════════════════════════════

ACTOR_SYSTEM_PROMPT = """你是足球博彩分析师(Actor)。根据输入的结构化数据, 输出严谨的预测。

## 核心原则

1. **市场是锚**: 市场赔率(Shin去水后)是已知最准的预测器。你有充分理由才能偏离市场。
2. **联赛风格为先**: 德甲大球多、意甲小球多、MLS主场强——联赛画像必须纳入推理。
3. **宁可不说, 不瞎说**: 数据不足时标注"参考, 不投注", 不要硬编。
4. **深盘保守**: 让球>1.5的深盘, 穿盘率远低于赔率暗示。

## 推理步骤

1. 读联赛画像 → 理解联赛特征(进球率/主胜率/风格)
2. 看ELO差 → 实力差距方向
3. 对市场 → 市场概率方向 vs ELO方向, 是否一致?
4. 参考DC数据 → 最可能比分、1-1和0-0概率
5. 结合联赛风格 → 修正(如: 意甲平局偏高、德甲大球偏多)
6. 深盘规则 → 触发则降档

## 输出格式 (严格JSON)

```json
{
  "prediction": {
    "direction": "主胜/平局/客胜",
    "confidence": "高/中/低",
    "home_win": 0.XX,
    "draw": 0.XX,
    "away_win": 0.XX,
    "expected_goals": X.X,
    "most_likely_score": "X-X",
    "over_25": 0.XX,
    "btts": 0.XX,
    "over_25_direction": "大2.5/小2.5",
    "btts_direction": "是/否"
  },
  "reasoning": "3-5句推理链, 说明市场方向、ELO、联赛风格的权重",
  "key_factors": ["因素1", "因素2"],
  "bet_suggestion": {
    "type": "1X2/大小球/BTTS/none",
    "pick": "主胜/大2.5/...",
    "reason": "..."
  },
  "warnings": ["警告1"]
}
```

如果数据不足无法判断, bet_suggestion.type 设为 "none", confidence 设为 "低"。
"""

REVIEWER_SYSTEM_PROMPT = """你是足球博彩审核员(Reviewer)。你的任务是审核Actor的预测, 发现盲点和过度自信。

## 审核清单

1. **市场偏离检查**: Actor是否无充分理由偏离市场>10%? 如果是 → disagree
2. **联赛风格冲突**: Actor是否忽略了联赛特征? (如意甲推大球、资格赛推深盘)
3. **数据不足**: ELO都是默认值? 联赛画像不匹配? → 降低confidence
4. **深盘风险**: 主胜概率>75%? 让球深度>1.5? → 标记风险
5. **逻辑一致性**: 方向预测和大小球预测是否自洽?

## 输出格式 (严格JSON)

```json
{
  "verdict": "agree/agree_with_reservation/disagree",
  "confidence_adjustment": "up/same/down",
  "adjusted_confidence": "高/中/低",
  "reasons": ["理由1", "理由2"],
  "warnings": ["警告1"],
  "suggested_changes": {
    "direction": null,
    "over_25_direction": null
  }
}
```
"""


# ══════════════════════════════════════════════════════════════
# LLM调用
# ══════════════════════════════════════════════════════════════

def _get_anthropic_key() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("ANTHROPIC_API_KEY", "")


def llm_actor(context: dict) -> dict:
    """阶段2: 让LLM做预测"""
    import anthropic

    key = _get_anthropic_key()
    if not key:
        logger.error("未找到 ANTHROPIC_API_KEY, 回退到数据推导")
        return _fallback_prediction(context)

    # 精简context, 去掉冗余信息
    compact = {
        "match": context["match"],
        "league": context["league_profile"],
        "elo": context["elo"],
        "market": context["market"],
        "reference": context["data_reference"],
        "rules": context["rule_check"],
    }

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model="claude-fable-5",
            max_tokens=1024,
            temperature=0.0,
            system=ACTOR_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"请根据以下数据预测这场比赛:\n\n```json\n{json.dumps(compact, ensure_ascii=False, indent=2)}\n```\n\n输出严格的JSON, 不要markdown包裹。"
            }],
        )
        text = resp.content[0].text.strip()
        # 清理可能的markdown包裹
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
    except Exception as e:
        logger.warning(f"LLM Actor失败: {e}, 回退到数据推导")
        return _fallback_prediction(context)


def llm_reviewer(context: dict, actor_output: dict) -> dict:
    """阶段3: 让第二个LLM审核预测"""
    import anthropic

    key = _get_anthropic_key()
    if not key:
        logger.warning("无API key, 跳过审核")
        return {"verdict": "agree", "confidence_adjustment": "same",
                "adjusted_confidence": actor_output.get("prediction", {}).get("confidence", "中"),
                "reasons": ["跳过审核(无API)"], "warnings": [],
                "suggested_changes": {}}

    compact = {
        "match": context["match"],
        "league": context["league_profile"],
        "elo": context["elo"],
        "market": context["market"],
        "rules": context["rule_check"],
    }

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model="claude-fable-5",
            max_tokens=512,
            temperature=0.0,
            system=REVIEWER_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"## 比赛数据\n```json\n{json.dumps(compact, ensure_ascii=False, indent=2)}\n```\n\n## Actor预测\n```json\n{json.dumps(actor_output, ensure_ascii=False, indent=2)}\n```\n\n请审核, 输出严格JSON。"
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
    except Exception as e:
        logger.warning(f"LLM Reviewer失败: {e}")
        return {"verdict": "agree", "confidence_adjustment": "same",
                "adjusted_confidence": actor_output.get("prediction", {}).get("confidence", "中"),
                "reasons": [f"审核异常: {e}"], "warnings": [],
                "suggested_changes": {}}


def _fallback_prediction(context: dict) -> dict:
    """无API时的纯数据推导 (保底方案)"""
    dc = context["data_reference"]["dixon_coles"]
    profile = context["league_profile"]
    market = context["market"]

    # 融合DC和市场
    if market:
        hw = dc["home_win"] * 0.4 + market["home"] * 0.6
        dr = dc["draw"] * 0.4 + market["draw"] * 0.6
        aw = dc["away_win"] * 0.4 + market["away"] * 0.6
    else:
        hw, dr, aw = dc["home_win"], dc["draw"], dc["away_win"]

    direction = "主胜" if hw >= max(dr, aw) else ("客胜" if aw >= max(hw, dr) else "平局")
    confidence = "高" if max(hw, dr, aw) > 0.50 else ("中" if max(hw, dr, aw) > 0.40 else "低")

    return {
        "prediction": {
            "direction": direction,
            "confidence": confidence,
            "home_win": round(hw, 3),
            "draw": round(dr, 3),
            "away_win": round(aw, 3),
            "expected_goals": round(context["data_reference"]["poisson_lambda"]["home"]
                                   + context["data_reference"]["poisson_lambda"]["away"], 1),
            "most_likely_score": dc["top3_scores"][0][0] if dc["top3_scores"] else "1-0",
            "over_25": round(dc["over_25"], 3),
            "btts": round(dc["btts"], 3),
            "over_25_direction": "大2.5" if dc["over_25"] > 0.5 else "小2.5",
            "btts_direction": "是" if dc["btts"] > 0.5 else "否",
        },
        "reasoning": "[回退模式] DC修正概率融合市场权重, 无LLM推理",
        "key_factors": ["市场赔率主导", "DC泊松参考"],
        "bet_suggestion": {"type": "none", "pick": None, "reason": "无LLM推理, 不做投注建议"},
        "warnings": ["⚠ 回退模式, 未经过LLM推理"],
    }


# ══════════════════════════════════════════════════════════════
# 阶段4: 规则引擎
# ══════════════════════════════════════════════════════════════

def apply_rules(context: dict, actor: dict, reviewer: dict) -> dict:
    """规则引擎: 硬约束兜底, 确保不和已知教训冲突

    规则优先级: 规则 > Reviewer > Actor
    """
    profile = context["league_profile"]
    market = context["market"]
    elo = context["elo"]
    rules = context["rule_check"]
    warnings = actor.get("warnings", []) + reviewer.get("warnings", [])

    # 1. 深盘规则 (8/6教训)
    if market and market["home"] > 0.78:
        warnings.append("深盘警告: 让球>1.5, 穿盘率低")
        if "深盘" not in str(warnings):
            pass  # already added

    if market and market["home"] > 0.85 and profile["over_25_rate"] < 0.55:
        warnings.append("🔴 禁止: 深盘+小球联赛, 不建议投注主胜穿盘")

    # 2. 数据不足标记
    if rules.get("data_quality", "").startswith("⚠"):
        warnings.append("数据不足: 球队ELO为联赛默认值, 预测置信度低")

    # 3. 低比分联赛+大球推荐冲突
    if profile["over_25_rate"] < 0.48 and actor.get("prediction", {}).get("over_25_direction") == "大2.5":
        warnings.append(f"⚠ 联赛风格冲突: {profile['name']}大球率仅{profile['over_25_rate']:.0%}, 推大球需谨慎")

    # 4. 资格赛主场弱规则
    if context["league_code"] == "CLQ" and actor.get("prediction", {}).get("direction") == "主胜":
        if actor.get("prediction", {}).get("confidence") == "高":
            warnings.append("⚠ 欧冠资格赛主场胜率仅40%, 主胜不宜高置信")

    # 5. Reviewer覆盖
    if reviewer.get("verdict") == "disagree":
        if actor.get("prediction", {}).get("confidence") == "高":
            actor["prediction"]["confidence"] = "中"
            warnings.append("Reviewer反对 → 降置信度")

    # 最终投注建议
    confidence = reviewer.get("adjusted_confidence",
                              actor.get("prediction", {}).get("confidence", "中"))

    bet_suggestion = actor.get("bet_suggestion", {})
    if bet_suggestion.get("type") != "none":
        if confidence == "低":
            bet_suggestion = {"type": "none", "pick": None, "reason": "置信度低, 不投注"}
        if len(warnings) >= 3:
            bet_suggestion["reason"] = bet_suggestion.get("reason", "") + " (多警告)"

    return {
        "final_prediction": actor.get("prediction", {}),
        "final_confidence": confidence,
        "reviewer_verdict": reviewer.get("verdict", "unknown"),
        "warnings": list(set(warnings)),  # 去重
        "bet_suggestion": bet_suggestion,
        "decision_summary": (
            f"方向{actor.get('prediction',{}).get('direction','?')} "
            f"| 置信{confidence} "
            f"| Reviewer:{reviewer.get('verdict','?')} "
            f"| 警告:{len(warnings)}个"
        ),
    }


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def run(match_limit: int = 10, use_llm: bool = True):
    """主流程: 数据→推理→审核→规则→输出"""
    logger.info("═══ 足球预测管线 v2.0 ═══")
    logger.info("架构: 数据(Python) → 推理(LLM) → 审核(LLM) → 规则引擎")

    # ── 阶段1: 数据 ──────────────────────────────────
    logger.info("── 阶段1: 数据采集 ──")
    matches = fetch_kambi_data()
    if not matches:
        matches = _load_cached_kambi()
    if not matches:
        logger.error("无比赛数据")
        return []

    matches = matches[:match_limit]
    logger.info(f"处理 {len(matches)} 场比赛")

    # ── 阶段2-4: 逐场处理 ──────────────────────────────
    results = []
    for i, match in enumerate(matches):
        logger.info(f"[{i+1}/{len(matches)}] {match.get('home','?')} vs {match.get('away','?')}")

        # 阶段1: 构建上下文
        context = build_match_context(match)

        # 阶段2: LLM推理
        actor_output = llm_actor(context) if use_llm else _fallback_prediction(context)

        # 阶段3: LLM审核
        reviewer_output = llm_reviewer(context, actor_output) if use_llm else {
            "verdict": "agree", "confidence_adjustment": "same",
            "adjusted_confidence": actor_output.get("prediction", {}).get("confidence", "中"),
            "reasons": [], "warnings": [], "suggested_changes": {},
        }

        # 阶段4: 规则引擎
        final = apply_rules(context, actor_output, reviewer_output)

        result = {
            "match": context["match"],
            "league": context["league"],
            "league_code": context["league_code"],
            "kickoff": context["kickoff"],
            "elo": context["elo"],
            "market": context["market"],
            "actor": actor_output,
            "reviewer": reviewer_output,
            "final": final,
        }
        results.append(result)

        # 简要输出
        f = final
        v_icon = {"agree": "✅", "agree_with_reservation": "⚠", "disagree": "🔴"}.get(
            reviewer_output.get("verdict", ""), "❓")
        print(f"  {v_icon} {f['final_prediction'].get('direction','?')} "
              f"| 置信{f['final_confidence']} "
              f"| {'✅投注' if f['bet_suggestion'].get('type') != 'none' else '参考'} "
              f"| {f['decision_summary'].split('|')[-1]}")

    # ── 保存结果 ──────────────────────────────────────
    out = {
        "pipeline": "v2.0",
        "generated_at": datetime.now().isoformat(),
        "architecture": "数据(Python) → 推理(LLM) → 审核(LLM) → 规则引擎",
        "match_count": len(results),
        "results": results,
    }

    json_path = ROOT / "data" / f"predictions_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    logger.info(f"结果保存: {json_path}")

    # 也输出到 today_final.json (前端用)
    (ROOT / "data" / "today_predictions.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # ── 统计 ──────────────────────────────────────────
    agrees = sum(1 for r in results if r["reviewer"].get("verdict") == "agree")
    bets = sum(1 for r in results if r["final"]["bet_suggestion"].get("type") != "none")
    logger.info(
        f"═══ 完成: {len(results)}场 | "
        f"双审一致{agrees} | 推荐投注{bets} | "
        f"Reviewer同意率{agrees}/{len(results)} ═══"
    )

    return results


def _load_cached_kambi() -> list[dict]:
    """加载缓存的Kambi数据"""
    path = ROOT / "data" / "kambi_odds.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="足球预测管线 v2.0")
    parser.add_argument("--matches", type=int, default=10,
                        help="处理比赛数 (默认10)")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过LLM (只用数据推导)")
    parser.add_argument("--review", action="store_true",
                        help="复盘昨日预测")
    args = parser.parse_args()

    if args.review:
        _review_yesterday()
    else:
        run(match_limit=args.matches, use_llm=not args.no_llm)


def _review_yesterday():
    """复盘: 对比预测vs实际赛果"""
    logger.info("═══ 复盘昨日预测 ═══")
    pred_file = ROOT / "data" / "today_predictions.json"
    if not pred_file.exists():
        logger.error("无昨日预测文件")
        return

    predictions = json.loads(pred_file.read_text(encoding="utf-8"))
    # TODO: 拉取实际赛果, 计算命中率
    logger.info(f"加载 {predictions.get('match_count', 0)} 场预测")
    logger.info("实际赛果拉取功能待完善")


if __name__ == "__main__":
    main()
