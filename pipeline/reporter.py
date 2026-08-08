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


# League code → display name
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

SIGNAL_CLASSES = {
    "high": "bet",
    "medium": "watch",
    "low": "watch",
    "none": "skip",
}

SIGNAL_TEXTS = {
    "high": "BET",
    "medium": "WATCH",
    "low": "REFERENCE",
    "none": "SKIP",
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

    # Load backtest Brier if available
    if backtest_brier is None:
        backtest_brier = _load_backtest_brier(output_dir)

    # Build template context
    match_cards = []
    for p in predictions:
        card = _build_match_card(p, analyst_notes)
        match_cards.append(card)

    # Summary stats
    total = len(match_cards)
    recommended = sum(1 for m in match_cards if m["recommendation"] == "recommended")
    reference_only = sum(1 for m in match_cards if m["recommendation"] == "reference")
    cold = sum(1 for m in match_cards if m["cold_start_flag"])

    # H/D/A pick distribution
    h_picks = sum(1 for m in match_cards if "Home" in m["pick"])
    d_picks = sum(1 for m in match_cards if "Draw" in m["pick"])
    a_picks = sum(1 for m in match_cards if "Away" in m["pick"])
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

    print(f"[OK] HTML report saved to {out_path}")
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

    home_team = p.get("home_team", "?")
    away_team = p.get("away_team", "?")
    league_code = p.get("league_code", "")
    league_name = LEAGUE_NAMES.get(league_code, league_code)
    cold_start = p.get("cold_start", False)

    # Probabilities — prefer Bayesian posterior if available, else model
    if bayes and "posterior" in bayes:
        post = bayes["posterior"]
        p_home = post.get("home", model.get("home_win", 0.33))
        p_draw = post.get("draw", model.get("draw", 0.34))
        p_away = post.get("away", model.get("away_win", 0.33))
    else:
        p_home = model.get("home_win", 0.33)
        p_draw = model.get("draw", 0.34)
        p_away = model.get("away_win", 0.33)

    # Pick from value detection
    pick_dir = value.get("best_direction", "none")
    if pick_dir == "home":
        pick = "Home Win"
    elif pick_dir == "draw":
        pick = "Draw"
    elif pick_dir == "away":
        pick = "Away Win"
    else:
        # Fall back to highest probability
        best_p = max(p_home, p_draw, p_away)
        if best_p == p_home:
            pick = "Home Win"
        elif best_p == p_draw:
            pick = "Draw"
        else:
            pick = "Away Win"

    # Confidence / signal
    confidence = value.get("confidence", "none")
    signal_class = SIGNAL_CLASSES.get(confidence, "skip")
    signal_text = SIGNAL_TEXTS.get(confidence, "SKIP")

    # Recommendation level
    if confidence == "high" and not cold_start:
        recommendation = "recommended"
    elif confidence in ("medium", "high"):
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

    # Analyst note
    match_key = f"{home_team} vs {away_team}"
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
        # Fallback: simple string interpolation
        return _SimpleTemplate(_read_template_content())

    return Jinja2Template(_read_template_content())


def _read_template_content() -> str:
    """Read template file content."""
    # Find template relative to project root
    template_paths = [
        "templates/report.html",
        os.path.join(os.path.dirname(__file__), "..", "templates", "report.html"),
    ]
    for tp in template_paths:
        if os.path.exists(tp):
            with open(tp, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("Could not find templates/report.html")


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

        # Stack-based parsing
        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("{% if ") and token.endswith(" %}"):
                var_name = token[6:-3].strip()
                condition = self._resolve(var_name, context)
                # Find matching endif/else
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
                # Parse: for ITEM in LIST
                m = _re.match(r'\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}', token)
                if m:
                    item_name = m.group(1)
                    list_name = m.group(2)
                    items = context.get(list_name, [])
                    # Find matching endfor
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
