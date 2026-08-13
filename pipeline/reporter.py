"""
HTML Report Generator v3.0

Renders predictions JSON → single professional HTML report via Jinja2.
Replaces 30+ manual HTML files with one template.

Usage:
    from pipeline.reporter import generate_report
    generate_report(predictions, output_path)
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any


# 联赛代码 → 显示名
LEAGUE_NAMES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
}

# League code → 中文名
LEAGUE_NAMES_CN = {
    "PL": "英超",
    "PD": "西甲",
    "BL1": "德甲",
    "SA": "意甲",
    "FL1": "法甲",
}

# English → 中文 team name mapping
TEAM_CN = {
    # 日职/日乙
    "Tokyo Verdy": "东京绿茵",
    "Kawasaki Frontale": "川崎前锋",
    "V-Varen Nagasaki": "长崎成功丸",
    "Kyoto Sanga": "京都不死鸟",
    "Montedio Yamagata": "山形山神",
    "Tochigi SC": "栃木SC",
    "Cottbus": "科特布斯",
    "Hannover": "汉诺威96",
    # 荷甲
    "Sparta Rotterdam": "鹿特丹斯巴达",
    "Feyenoord": "费耶诺德",
    "Zwolle": "兹沃勒",
    "Ajax": "阿贾克斯",
    "Groningen": "格罗宁根",
    "Utrecht": "乌得勒支",
    "Heerenveen": "海伦芬",
    "Twente": "特温特",
    # 德乙
    "St Pauli": "圣保利",
    "Greuther Furth": "菲尔特",
    "Nurnberg": "纽伦堡",
    "Dresden": "德累斯顿",
    # 瑞典超
    "Hammarby": "哈马比",
    "Hacken": "赫根",
    "Halmstads": "哈尔姆斯塔德",
    "GAIS": "哥德堡盖斯",
    "IFK Goteborg": "IFK哥德堡",
    "Kalmar": "卡尔马",
    "Malmo": "马尔默",
    "Degerfors": "代格福什",
    # 芬超
    "KuPS": "库普斯",
    "TPS": "TPS图尔库",
    "Inter Turku": "国际图尔库",
    "Lahti": "拉赫蒂",
    "Ilves": "伊尔韦斯",
    "Mariehamn": "玛丽港",
    "AC Oulu": "AC奥卢",
    "HJK": "HJK赫尔辛基",
    "HJK Helsinki": "HJK赫尔辛基",
    # 挪超
    "Lillestrom": "利勒斯特伦",
    "Rosenborg": "罗森博格",
    "HamKam": "汉坎",
    "Aalesund": "奥勒松",
    "Kristiansund": "克里斯蒂安松",
    "Molde": "莫尔德",
    # 葡超
    "Porto": "波尔图",
    "Alverca": "阿尔维卡",
    "Benfica": "本菲卡",
    "Viseu": "维塞乌",
    "Gil Vicente": "吉维森特",
    "Rio Ave": "里奥阿维",
    "Moreirense": "莫雷伦斯",
    "Sp Braga": "布拉加",
    "Braga": "布拉加",
    # 巴甲
    "Santos": "桑托斯",
    "Athletico-PR": "巴拉纳竞技",
    "Flamengo": "弗拉门戈",
    "Guimaraes": "吉马良斯",
    "Vitoria Guimaraes": "吉马良斯",
    "Vitoria": "维多利亚",
    "Cruzeiro": "克鲁塞罗",
    "Mirassol": "米拉索尔",
    "Bahia": "巴伊亚",
    "Vasco": "瓦斯科达伽马",
    "Palmeiras": "帕尔梅拉斯",
    "Internacional": "巴西国际",
    "Bragantino": "布拉甘蒂诺",
    "Corinthians": "科林蒂安",
    # 美职联/LCUP
    "Austin FC": "奥斯汀FC",
    "Puebla": "普埃布拉",
    "San Diego FC": "圣地亚哥FC",
    "Tijuana": "蒂华纳",
    "Club America": "美洲",
    "Portland Timbers": "波特兰伐木者",
    "IK Sirius": "天狼星",
    "IF Brommapojkarna": "布鲁马波卡纳",
    "Vasteras SK": "韦斯特罗斯",
    "Västerås SK": "韦斯特罗斯",
    "Djurgardens IF": "佐加顿斯",
    "Djurgårdens IF": "佐加顿斯",
    "Santa Clara": "圣克拉拉",
    "Nacional": "葡萄牙国民",
    # 俄超/其他
    "CSKA Moscow": "莫斯科中央陆军",
    "Spartak Moscow": "莫斯科斯巴达",
    "Zenit": "泽尼特",
    "Krasnodar": "克拉斯诺达尔",
    "Lokomotiv Moscow": "莫斯科火车头",
    "Dinamo Moscow": "莫斯科迪纳摩",
}

def _cn(home_team: str, away_team: str) -> tuple[str, str]:
    """Return Chinese team names for a match pair."""
    return TEAM_CN.get(home_team, home_team), TEAM_CN.get(away_team, away_team)

SIGNAL_CLASSES = {
    "high": "bet",
    "medium": "watch",
    "low": "watch",
    "none": "skip",
}

SIGNAL_TEXTS = {
    "high": "投注",
    "medium": "关注",
    "low": "参考",
    "none": "跳过",
}


def generate_report(
    predictions: list[dict],
    output_dir: str = "data/output",
    output_name: str | None = None,
    backtest_brier: float | None = None,
    analyst_notes: dict[str, str] | None = None,
) -> str:
    """Generate HTML report from predictions list.

    Args:
        predictions: list of prediction dicts from cmd_predict
        output_dir: output directory
        output_name: output filename (defaults to predictions_YYYY-MM-DD.html)
        backtest_brier: optional backtest Brier score for footer
        analyst_notes: optional dict of "Home vs Away" → note text (from LLM)

    Returns:
        Path to generated HTML file
    """
    today = date.today().isoformat()
    out_name = output_name or f"predictions_{today}.html"
    out_path = os.path.join(output_dir, out_name)

    # 如可用则加载回测Brier
    if backtest_brier is None:
        backtest_brier = _load_backtest_brier(output_dir)

    # 构建模板上下文
    match_cards = []
    for p in predictions:
        card = _build_match_card(p, analyst_notes)
        match_cards.append(card)

    # Summary stats
    total = len(match_cards)
    recommended = sum(1 for m in match_cards if m["recommendation"] == "recommended")
    reference_only = sum(1 for m in match_cards if m["recommendation"] == "reference")
    cold = sum(1 for m in match_cards if m["cold_start_flag"])

    # 胜平负方向分布
    h_picks = sum(1 for m in match_cards if m["pick"] == "主胜")
    d_picks = sum(1 for m in match_cards if m["pick"] == "平局")
    a_picks = sum(1 for m in match_cards if m["pick"] == "客胜")
    direction_dist = f"{h_picks}/{d_picks}/{a_picks}"

    context = {
        "date": today,
        "backtest_brier": f"{backtest_brier:.4f}" if backtest_brier else None,
        "total_matches": total,
        "recommended": recommended,
        "reference": reference_only,
        "cold_start": cold,
        "direction_dist": direction_dist,
        "matches": match_cards,
    }

    # Render template
    html = _render_template(context)
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML报告已保存 → {out_path}")
    return out_path


def _build_match_card(
    p: dict,
    analyst_notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build template context for a single match card."""
    model = p.get("model", {})
    value = p.get("value") or {}
    bayes = p.get("bayesian") or {}
    odds_data = p.get("odds") or {}

    home_team_en = p.get("home_team", "?")
    away_team_en = p.get("away_team", "?")
    home_team, away_team = _cn(home_team_en, away_team_en)
    league_code = p.get("league_code", "")
    league_name = LEAGUE_NAMES.get(league_code, league_code)
    cold_start = p.get("cold_start", False)

    # 概率 — 优先贝叶斯后验, 否则用模型
    if bayes and "posterior" in bayes:
        post = bayes["posterior"]
        p_home = post.get("home", model.get("home_win", 0.33))
        p_draw = post.get("draw", model.get("draw", 0.34))
        p_away = post.get("away", model.get("away_win", 0.33))
    else:
        p_home = model.get("home_win", 0.33)
        p_draw = model.get("draw", 0.34)
        p_away = model.get("away_win", 0.33)

    # 从价值检测取方向
    pick_dir = value.get("best_direction", "none")
    if pick_dir == "home":
        pick = "主胜"
    elif pick_dir == "draw":
        pick = "平局"
    elif pick_dir == "away":
        pick = "客胜"
    else:
        # 兜底: 最高概率方向
        best_p = max(p_home, p_draw, p_away)
        if best_p == p_home:
            pick = "主胜"
        elif best_p == p_draw:
            pick = "平局"
        else:
            pick = "客胜"

    # 置信度 / 信号
    confidence = value.get("confidence", "none")

    # 冷启动场次: 模型edge是噪音 → 覆盖信号
    if cold_start and confidence != "none":
        signal_class = "cold"
        signal_text = "冷启动"
        confidence = "low"  # downgrade edge for recommendation logic
    else:
        signal_class = SIGNAL_CLASSES.get(confidence, "skip")
        signal_text = SIGNAL_TEXTS.get(confidence, "SKIP")

    # 推荐等级
    if confidence == "high" and not cold_start:
        recommendation = "recommended"
    elif confidence in ("medium", "high") or (cold_start and confidence != "none"):
        recommendation = "reference"
    else:
        recommendation = "skip"

    # Kelly
    kelly_val = value.get("kelly", 0) or 0
    kelly_text = f"{kelly_val:.2%}" if kelly_val > 0 else None
    kelly_class = "pos" if kelly_val > 0 else "neg"

    # Edge
    edges = {
        "home": value.get("home_edge", 0) or 0,
        "draw": value.get("draw_edge", 0) or 0,
        "away": value.get("away_edge", 0) or 0,
    }
    best_edge_dir = max(edges, key=edges.get)
    best_edge_val = edges[best_edge_dir]
    edge_pct = f"{best_edge_val:.1%}" if best_edge_val > 0 else None

    # Market odds
    market_odds_str = None
    if odds_data:
        h = odds_data.get("home", 0)
        d = odds_data.get("draw", 0)
        a = odds_data.get("away", 0)
        if h and d and a:
            market_odds_str = f"{h:.2f}/{d:.2f}/{a:.2f}"

    # Expected goals
    lam_h = model.get("lambda_home", 0)
    lam_a = model.get("lambda_away", 0)
    eg_text = f"{lam_h:.2f} - {lam_a:.2f}" if lam_h > 0 else None

    # Top score
    top_scores = model.get("top_5_scores", [])
    top_score_str = top_scores[0][0] if top_scores else None

    # ELO
    elo_diff = p.get("elo_diff", 0)

    # 分析师注释 — 按英文名查(键为英文)
    match_key = f"{home_team_en} vs {away_team_en}"
    analyst_note = (analyst_notes or {}).get(match_key)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "league": league_name,
        "p_home": f"{p_home:.1%}",
        "p_draw": f"{p_draw:.1%}",
        "p_away": f"{p_away:.1%}",
        "p_home_pct": round(p_home * 100, 1),
        "p_draw_pct": round(p_draw * 100, 1),
        "p_away_pct": round(p_away * 100, 1),
        "over25": f"{model.get('over_25', 0):.1%}",
        "btts": f"{model.get('btts', 0):.1%}",
        "eg": eg_text or "N/A",
        "top_score": top_score_str or "N/A",
        "elo_diff": f"{elo_diff:+.0f}" if elo_diff else "0",
        "market_odds": market_odds_str,
        "pick": pick,
        "signal_class": signal_class,
        "signal_text": signal_text,
        "recommendation": recommendation,
        "kelly_fraction": kelly_text,
        "kelly_class": kelly_class,
        "edge_direction": best_edge_dir.title() if best_edge_val > 0 else None,
        "edge_pct": edge_pct,
        "cold_start_flag": cold_start,
        "analyst_note": analyst_note,
    }


def _render_template(context: dict) -> str:
    """Render the Jinja2 template with given context."""
    template = _get_template()
    return template.render(**context)


def _get_template():
    """Lazy-load Jinja2 template."""
    try:
        from jinja2 import Template as Jinja2Template
    except ImportError:
        # 兜底: 简单字符串插值
        return _SimpleTemplate(_read_template_content())

    return Jinja2Template(_read_template_content())


def _read_template_content(template_name: str = "report.html") -> str:
    """Read template file content."""
    template_paths = [
        f"templates/{template_name}",
        os.path.join(os.path.dirname(__file__), "..", "templates", template_name),
    ]
    for tp in template_paths:
        if os.path.exists(tp):
            with open(tp, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(f"Could not find templates/{template_name}")


def generate_review_report(
    matched: list[dict],
    output_dir: str = "data/output",
    date_str: str | None = None,
    elo_changes: list[dict] | None = None,
    dimension_summary: str = "",
) -> str:
    """Generate review HTML report from matched predictions and results.

    Args:
        matched: list from result_fetcher.match_predictions_to_results()
        output_dir: output directory
        date_str: date string (defaults to today)
        elo_changes: optional list of {team, old, new, delta, reason}
        dimension_summary: 5维度复盘纯文本 (来自dimension_review)

    Returns:
        Path to generated HTML file
    """
    from datetime import date
    today = date_str or date.today().isoformat()
    out_path = os.path.join(output_dir, f"review_{today}.html")

    if not matched:
        os.makedirs(output_dir, exist_ok=True)
        html = f"<html><body><h1>No matched results for {today}</h1></body></html>"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return out_path

    n_total = len(matched)
    n_matched = sum(1 for m in matched if m.get("matched"))

    # ---- 评估指标 ----
    import math
    brier_sum = 0.0
    logloss_sum = 0.0
    correct = 0
    total_pl = 0.0
    n_bets = 0

    # 方向统计
    h_total = h_correct = 0
    d_total = d_correct = 0
    a_total = a_correct = 0

    match_rows = []
    for m in matched:
        pred = m["predicted"]
        actual = m["actual"]
        value = m.get("value") or {}
        home_goals = m.get("home_goals")
        away_goals = m.get("away_goals")

        # Brier: 三个结果的均方误差
        outcomes = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}
        actual_vec = outcomes.get(actual, [0, 0, 0])
        pred_vec = [pred["home_win"], pred["draw"], pred["away_win"]]
        brier_sum += sum((p - a) ** 2 for p, a in zip(pred_vec, actual_vec)) / 3

        # 对数损失: -ln(实际结果的概率)
        idx = {"H": 0, "D": 1, "A": 2}.get(actual, 0)
        p_actual = max(pred_vec[idx], 0.001)
        logloss_sum += -math.log(p_actual)

        # Accuracy
        best_pred = max(
            ("H", pred["home_win"]),
            ("D", pred["draw"]),
            ("A", pred["away_win"]),
            key=lambda x: x[1],
        )[0]
        if best_pred == actual:
            correct += 1

        # Directional
        if actual == "H":
            h_total += 1
            if best_pred == "H":
                h_correct += 1
        elif actual == "D":
            d_total += 1
            if best_pred == "D":
                d_correct += 1
        elif actual == "A":
            a_total += 1
            if best_pred == "A":
                a_correct += 1

        # 盈亏: 模拟最优方向1单位投注
        bet_dir = value.get("best_direction", "none")
        kelly = value.get("kelly", 0) or 0
        pl = 0.0
        # 投注方向映射到实际代码
        bet_to_actual = {"home": "H", "draw": "D", "away": "A"}
        if bet_dir != "none" and kelly > 0:
            n_bets += 1
            edge = value.get(f"{bet_dir}_edge", 0) or 0
            market_prob = pred_vec[{"home": 0, "draw": 1, "away": 2}[bet_dir]] - edge
            if market_prob > 0.01:
                odds = 1.0 / market_prob
                stake = kelly
                if bet_to_actual.get(bet_dir) == actual:
                    pl = stake * (odds - 1)
                else:
                    pl = -stake
            total_pl += pl

        # Match row
        pick_dir = value.get("best_direction", "none")
        if pick_dir == "home":
            pick = "H"
        elif pick_dir == "draw":
            pick = "D"
        elif pick_dir == "away":
            pick = "A"
        else:
            pick = best_pred

        if pick == actual:
            outcome = "hit"
            verdict = "✓ 命中"
        elif pick != best_pred and best_pred == actual:
            outcome = "push"
            verdict = "△ 走水"
        else:
            outcome = "miss"
            verdict = "✗ 失误"

        prob_pick = pred_vec[{"H": 0, "D": 1, "A": 2}.get(pick, 0)]

        home_cn, away_cn = _cn(m["home_team"], m["away_team"])
        match_rows.append({
            "home_team": home_cn,
            "away_team": away_cn,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "actual": actual,
            "pred_h": f"{pred['home_win']:.1%}",
            "pred_d": f"{pred['draw']:.1%}",
            "pred_a": f"{pred['away_win']:.1%}",
            "pred_pick_prob": f"{prob_pick:.1%}",
            "pick": pick,
            "outcome": outcome,
            "verdict": verdict,
            "pl": f"{pl:+.3f}u" if pl != 0 else None,
            "pl_class": "won" if pl > 0 else "lost" if pl < 0 else "",
            "cold_start": m.get("cold_start", False),
        })

    # Aggregate
    n = n_matched
    brier_val = round(brier_sum / n, 4) if n > 0 else 0
    logloss_val = round(logloss_sum / n, 4) if n > 0 else 0
    accuracy_val = correct / n if n > 0 else 0

    total_pl_val = round(total_pl, 2)
    roi_val = f"{total_pl / n_bets:+.1%}" if n_bets > 0 else "N/A"

    def _cls(v, low_good=True):
        if low_good:
            return "good" if v < 0.65 else "warn" if v < 0.70 else "bad"
        return "good" if v > 0.55 else "warn" if v > 0.45 else "bad"

    context = {
        "date": today,
        "n_total": n_total,
        "n_matched": n_matched,
        "brier": f"{brier_val:.4f}",
        "brier_class": _cls(brier_val),
        "logloss": f"{logloss_val:.4f}",
        "logloss_class": _cls(logloss_val * 0.9),
        "accuracy": f"{accuracy_val:.1%}",
        "accuracy_class": _cls(1 - accuracy_val, low_good=False),
        "total_pl": f"{total_pl_val:+.2f}u",
        "pl_class": "good" if total_pl_val > 0 else "bad" if total_pl_val < 0 else "",
        "roi": roi_val,
        "roi_class": "good" if total_pl_val > 0 else "bad",
        "h_correct": h_correct, "h_total": h_total,
        "h_rate": f"{h_correct/h_total:.1%}" if h_total > 0 else "N/A",
        "d_correct": d_correct, "d_total": d_total,
        "d_rate": f"{d_correct/d_total:.1%}" if d_total > 0 else "N/A",
        "a_correct": a_correct, "a_total": a_total,
        "a_rate": f"{a_correct/a_total:.1%}" if a_total > 0 else "N/A",
        "h_pct": round(h_total / n * 100) if n > 0 else 33,
        "d_pct": round(d_total / n * 100) if n > 0 else 34,
        "a_pct": round(a_total / n * 100) if n > 0 else 33,
        "matches": match_rows,
        "elo_changes": elo_changes or [],
        "dimension_summary": dimension_summary,
    }

    # Render
    template = _get_review_template()
    html = template.render(**context)

    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] 复盘报告已保存 → {out_path}")
    return out_path


def _get_review_template():
    """Lazy-load review Jinja2 template."""
    try:
        from jinja2 import Template as Jinja2Template
    except ImportError:
        return _SimpleTemplate(_read_template_content("review.html"))
    return Jinja2Template(_read_template_content("review.html"))


def update_tracking_file(
    matched: list[dict],
    date_str: str,
    output_dir: str = "data/output",
    elo_summary: dict | None = None,
) -> dict:
    """Append daily review results to cumulative tracking file.

    Args:
        matched: matched predictions and results
        date_str: date of predictions
        output_dir: output directory
        elo_summary: optional ELO change summary

    Returns:
        Updated tracking data dict
    """
    tracking_path = os.path.join(output_dir, "daily_tracking.json")

    # Load existing
    if os.path.exists(tracking_path):
        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)
    else:
        tracking = {"days": [], "cumulative": {}}

    # 计算当日指标
    n = len(matched)
    if n == 0:
        return tracking

    correct = 0
    brier_sum = 0.0
    for m in matched:
        pred = m["predicted"]
        actual = m["actual"]
        outcomes = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}
        actual_vec = outcomes.get(actual, [0, 0, 0])
        pred_vec = [pred["home_win"], pred["draw"], pred["away_win"]]
        brier_sum += sum((p - a) ** 2 for p, a in zip(pred_vec, actual_vec)) / 3

        best_pred = max(
            ("H", pred["home_win"]),
            ("D", pred["draw"]),
            ("A", pred["away_win"]),
            key=lambda x: x[1],
        )[0]
        if best_pred == actual:
            correct += 1

    day_entry = {
        "date": date_str,
        "matches": n,
        "brier": round(brier_sum / n, 4),
        "accuracy": round(correct / n, 4),
        "cold_start_count": sum(1 for m in matched if m.get("cold_start")),
    }

    if elo_summary:
        day_entry["elo_updates"] = elo_summary.get("teams_updated", 0)

    # 同日记录替换, 否则追加
    existing_idx = None
    for i, d in enumerate(tracking["days"]):
        if d.get("date") == date_str:
            existing_idx = i
            break
    if existing_idx is not None:
        tracking["days"][existing_idx] = day_entry
    else:
        tracking["days"].append(day_entry)

    # 更新累计值
    all_n = sum(d["matches"] for d in tracking["days"])
    all_brier = sum(d["brier"] * d["matches"] for d in tracking["days"]) / all_n if all_n > 0 else 0
    all_acc = sum(d["accuracy"] * d["matches"] for d in tracking["days"]) / all_n if all_n > 0 else 0
    tracking["cumulative"] = {
        "total_days": len(tracking["days"]),
        "total_matches": all_n,
        "avg_brier": round(all_brier, 4),
        "avg_accuracy": round(all_acc, 4),
    }

    with open(tracking_path, "w", encoding="utf-8") as f:
        json.dump(tracking, f, ensure_ascii=False, indent=2)

    print(f"[OK] 跟踪已更新: {tracking['cumulative']}")
    return tracking


class _SimpleTemplate:
    """Minimal Jinja2-free template renderer.

    Supports: {{ var }}, {% if var %}...{% endif %}, {% for m in list %}...{% endfor %}
    Used as fallback when jinja2 is not installed.
    """
    def __init__(self, source: str):
        import re
        self.source = source
        self._token_re = re.compile(
            r'(\{%\s*if\s+(\w+(?:\.\w+)*)\s*%\})'
            r'|(\{%\s*else\s*%\})'
            r'|(\{%\s*endif\s*%\})'
            r'|(\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\})'
            r'|(\{%\s*endfor\s*%\})'
            r'|(\{\{\s*(\w+(?:\.\w+(?:\(\))?)?)\s*\}\})'
        )

    def render(self, **context) -> str:
        return self._render_block(self.source, context)

    def _render_block(self, template: str, context: dict) -> str:
        import re as _re
        result = []

        # Tokenize
        tokens = _re.split(
            r'(\{%[^%]*%\}|\{\{[^}]*\}\})',
            template,
        )

        # 基于栈的解析
        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("{% if ") and token.endswith(" %}"):
                var_name = token[6:-3].strip()
                condition = self._resolve(var_name, context)
                # 查找匹配的endif/else
                depth = 1
                j = i + 1
                else_idx = -1
                endif_idx = -1
                while j < len(tokens):
                    t = tokens[j]
                    if t.startswith("{% if "):
                        depth += 1
                    elif t.startswith("{% endif %}"):
                        depth -= 1
                        if depth == 0:
                            endif_idx = j
                            break
                    elif t.startswith("{% else %}") and depth == 1:
                        else_idx = j
                    j += 1

                if condition:
                    start = i + 1
                    end = else_idx if else_idx >= 0 else endif_idx
                    block = "".join(tokens[start:end])
                    result.append(self._render_block(block, context))
                elif else_idx >= 0:
                    start = else_idx + 1
                    block = "".join(tokens[start:endif_idx])
                    result.append(self._render_block(block, context))
                i = endif_idx + 1

            elif token.startswith("{% for ") and token.endswith(" %}"):
                # 解析: for ITEM in LIST
                m = _re.match(r'\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}', token)
                if m:
                    item_name = m.group(1)
                    list_name = m.group(2)
                    items = context.get(list_name, [])
                    # 查找匹配的endfor
                    depth = 1
                    j = i + 1
                    while j < len(tokens):
                        t = tokens[j]
                        if t.startswith("{% for "):
                            depth += 1
                        elif t.startswith("{% endfor %}"):
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    block_tokens = tokens[i + 1:j]
                    block_src = "".join(block_tokens)
                    for item in items:
                        item_ctx = dict(context)
                        item_ctx[item_name] = item
                        result.append(self._render_block(block_src, item_ctx))
                    i = j + 1
                else:
                    i += 1

            elif token.startswith("{% else %}") or token.startswith("{% endif %}") or token.startswith("{% endfor %}"):
                i += 1

            elif token.startswith("{{ ") and token.endswith(" }}"):
                var_name = token[3:-3].strip()
                val = self._resolve(var_name, context)
                result.append(str(val) if val is not None else "")
                i += 1

            else:
                result.append(token)
                i += 1

        return "".join(result)

    def _resolve(self, var_path: str, context: dict) -> Any:
        """Resolve a dotted variable path like 'm.home_team' or 'backtest_brier'."""
        parts = var_path.split(".")
        val = context
        for part in parts:
            if val is None:
                return None
            if isinstance(val, dict):
                val = val.get(part)
            elif hasattr(val, part):
                val = getattr(val, part)
            else:
                return None
        return val


def _load_backtest_brier(output_dir: str) -> float | None:
    """Load backtest Brier score from report."""
    brier_path = os.path.join(output_dir, "backtest_report.json")
    if not os.path.exists(brier_path):
        return None
    try:
        with open(brier_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        return report.get("summary", {}).get("avg_brier")
    except Exception:
        return None
