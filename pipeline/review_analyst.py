# -*- coding: utf-8 -*-
"""
复盘分析师 (2026-08-17 新增)

真正的复盘 = 预测vs结果对照 + 错因归因:
  - 对照昨天所有预测 (胜平负/大小球/让球/波胆/半全场) 与赛果
  - LLM 归因: 爆冷? 赔率变动没注意? 伤停? 冷启动? 战意? 模型盲区?
  - 输出 review_analysis_YYYY-MM-DD.html (网页复盘分析页)

用法:
  python pipeline/review_analysis.py <日期YYYY-MM-DD>   # 独立重跑 (幂等)
流水线: pipeline.py cmd_review 末尾自动调用 generate_review_analysis()
"""
from __future__ import annotations

import glob
import html as _html
import json
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CSS = """
  :root { --bg:#0b0f1a; --card:#121a2c; --line:#1e2a42; --txt:#e9eef8; --dim:#8d99b0;
          --green:#34d399; --amber:#fbbf24; --blue:#5ea8ff; --red:#f87171; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:radial-gradient(1000px 400px at 20% -10%, rgba(94,168,255,.12), transparent 60%), var(--bg);
         color:var(--txt); min-height:100vh; padding:28px 16px 40px; line-height:1.6; }
  .container { max-width:860px; margin:0 auto; }
  .hero { text-align:center; padding:30px 10px 20px; }
  .badge { display:inline-block; font-size:.8rem; color:#bfd7ff;
           background:linear-gradient(135deg, rgba(94,168,255,.16), rgba(167,139,250,.14));
           border:1px solid rgba(94,168,255,.35); padding:5px 16px; border-radius:999px; }
  .hero h1 { font-size:1.9rem; font-weight:800; margin-top:12px;
             background:linear-gradient(90deg,#e9eef8,#9ec4ff 60%,#c4b5fd);
             -webkit-background-clip:text; background-clip:text; color:transparent; }
  .hero-sub { color:var(--dim); font-size:.85rem; margin-top:8px; }
  .summary { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:14px 0 24px; }
  .s-box { background:linear-gradient(180deg,var(--card),#101725); border:1px solid var(--line);
           border-radius:12px; padding:12px 6px; text-align:center; }
  .s-box .v { font-size:1.3rem; font-weight:800; }
  .s-box .l { font-size:.72rem; color:var(--dim); }
  .hit { color:var(--green); } .miss { color:var(--red); }
  .match { background:linear-gradient(180deg,var(--card),#101725); border:1px solid var(--line);
           border-radius:14px; padding:18px; margin:14px 0; }
  .m-head { display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; }
  .m-teams { font-size:1.2rem; font-weight:800; }
  .m-score { font-size:1.3rem; font-weight:800; color:var(--blue); }
  table { width:100%; border-collapse:collapse; margin-top:12px; font-size:.88rem; }
  th, td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
  th { color:#a8c7f0; background:#0e1526; font-size:.78rem; }
  td.hit { } td.miss { color:#fca5a5; }
  .drift { margin-top:10px; background:#0e1526; border:1px solid var(--line); border-radius:10px;
           padding:10px 14px; font-size:.82rem; color:var(--dim); white-space:pre-wrap; }
  .ai { margin-top:10px; background:#0a1120; border:1px solid rgba(94,168,255,.35); border-radius:10px;
        padding:12px 16px; font-size:.9rem; white-space:pre-wrap; }
  .ai b { color:var(--blue); }
  .footer { text-align:center; color:var(--dim); font-size:.78rem; margin-top:26px; }
  a { color:#38bdf8; text-decoration:none; }
"""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_drift(date_str: str) -> dict:
    """全天赔率变动 (快照首尾对比): (home,away) -> 描述字符串"""
    snaps = sorted(glob.glob(os.path.join("data", "state", "odds_snapshots", f"snapshot_{date_str}_*.json")))
    if len(snaps) < 2:
        return {}
    first, last = snaps[0], snaps[-1]
    a_list = _load_json(first) or []
    b_list = _load_json(last) or []
    b_map = {(m.get("home_team"), m.get("away_team")): m for m in b_list}
    out = {}
    for m in a_list:
        key = (m.get("home_team"), m.get("away_team"))
        bm = b_map.get(key)
        if not bm:
            continue
        oa, ob = m.get("odds") or {}, bm.get("odds") or {}
        lines = []
        if oa.get("home") and ob.get("home"):
            lines.append(
                f"SPF: 主{oa['home']:.2f}→{ob['home']:.2f} 平{oa.get('draw', 0):.2f}→{ob.get('draw', 0):.2f} 客{oa['away']:.2f}→{ob['away']:.2f}"
            )
        if m.get("over_odds") and bm.get("over_odds"):
            lines.append(
                f"大小球: 大{m['over_odds']:.2f}→{bm['over_odds']:.2f} 小{m['under_odds']:.2f}→{bm['under_odds']:.2f}"
            )
        out[key] = "\n".join(lines)
    return out


def _query_postmortem(prompt: str) -> str:
    """赛后归因专用 LLM 调用 (独立系统提示, 不用赛前分析师人格)"""
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=DEEPSEEK_API_KEY, disable_thinking_by_default=True)
        resp = client.chat(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content":
                    "你是足球赛后复盘分析师。比赛已经踢完, 赛果已给出。严格按用户要求输出三段: "
                    "结果对照 / 错因归因 / 教训。纯中文, 每段2-3句, 不写概率数字, 不写赛前建议。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=320,
            temperature=0.7,
        )
        msg = resp.get("message") or {}
        return (msg.get("content") or "").strip()
    except Exception as e:
        print(f"  [复盘LLM] 失败: {e}")
        return ""


def _split_ai(note: str) -> dict:
    """把 LLM 复盘输出拆成三段"""
    parts = {"对照": "", "归因": "", "教训": ""}
    if not note:
        return parts
    cur = ""
    for line in note.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("结果对照"):
            cur = "对照"
            rest = line[len("结果对照"):].lstrip(":： ").strip()
        elif line.startswith("错因归因"):
            cur = "归因"
            rest = line[len("错因归因"):].lstrip(":： ").strip()
        elif line.startswith("教训"):
            cur = "教训"
            rest = line[len("教训"):].lstrip(":： ").strip()
        else:
            rest = line
        if rest:
            parts[cur or "对照"] = (parts[cur or "对照"] + "\n" + rest).strip()
    return parts


def _build_postmortem_prompt(pred: dict, result: dict, drift_txt: str) -> str:
    home = pred.get("home_team", "?")
    away = pred.get("away_team", "?")
    m = pred.get("model", {})
    val = pred.get("value") or {}
    bayes = pred.get("bayesian") or {}
    odds = pred.get("odds") or {}
    post = bayes.get("posterior") or {}

    lines = [
        f"你是足球赛后复盘分析师。比赛已踢完, 请做\"预测vs结果\"对照复盘 (不是赛前分析)。",
        "",
        f"比赛: {home} vs {away} ({pred.get('league_code', '')})",
        "赛前预测(终盘):",
        f"- 胜平负: 主{m.get('home_win', 0):.1%} 平{m.get('draw', 0):.1%} 客{m.get('away_win', 0):.1%}",
    ]
    if odds.get("home"):
        lines.append(f"- 欧赔: 主{odds['home']:.2f}/平{odds.get('draw', 0):.2f}/客{odds['away']:.2f}")
    if post:
        lines.append(f"- 贝叶斯后验: 主{post.get('home', 0):.1%} 平{post.get('draw', 0):.1%} 客{post.get('away', 0):.1%}")
    if val:
        lines.append(f"- 1X2价值: {val.get('best_direction')} (edge {val.get('home_edge', 0) if val.get('best_direction') == 'home' else val.get('away_edge', 0) if val.get('best_direction') == 'away' else val.get('draw_edge', 0):+.1%})")
    ou_v = pred.get("ou_value")
    if ou_v:
        lines.append(f"- 大小球: {ou_v['side']} (模型{ou_v['model']:.0%} vs 市场{ou_v['market']:.0%}, edge {ou_v.get('edge', 0):+.1%})")
    ah = pred.get("ah_handicap") or {}
    if ah.get("edge") and ah["edge"].get("best_pick"):
        e = ah["edge"]
        lines.append(f"- 让球盘: 让{ah.get('goal_line')}球, 模型倾向 {e['best_pick']} (edge {e.get('edge', 0):+.1%})")
    cs = pred.get("cs_value") or []
    if cs:
        lines.append("- 波胆价值: " + " ".join(f"{v['score']}(模型{v['model']:.0%}vs市场{v['market']:.0%})" for v in cs))
    ht = pred.get("ht_ft_odds") or {}
    if ht:
        top = sorted(ht.items(), key=lambda x: x[1])[:2]
        lines.append("- 半全场最低赔: " + " ".join(f"{k}@{v:.2f}" for k, v in top))
    lines.append(f"- 冷启动: {'是(模型无数据, 市场定价为主)' if pred.get('cold_start') else '否'}")
    if drift_txt:
        lines.append("全天赔率变动:")
        lines.append(drift_txt)
    lines.append("")
    lines.append(f"实际赛果: {result.get('home_goals', '?')} - {result.get('away_goals', '?')} ({result.get('result', '?')})")
    lines.append("")
    lines.append("请输出 (纯中文, 每段2-3句, 不写概率数字):")
    lines.append("结果对照: (哪几条预测命中, 哪几条错了)")
    lines.append("错因归因: (是爆冷? 赔率变动没注意? 伤停? 冷启动? 战意? 还是模型盲区?)")
    lines.append("教训: (下回遇到类似情况该怎么做)")
    return "\n".join(lines)


def _find_result(pred: dict, results: list[dict]) -> dict | None:
    from pipeline.result_fetcher import _teams_match
    from pipeline.data_loader import normalize_team_name
    ph = normalize_team_name(pred.get("home_team", ""))
    pa = normalize_team_name(pred.get("away_team", ""))
    for r in results:
        rh = normalize_team_name(r.get("home_team", ""))
        ra = normalize_team_name(r.get("away_team", ""))
        if _teams_match(ph, rh) and _teams_match(pa, ra):
            return r
    return None


def _score_line(actual: str) -> str:
    if actual == "H":
        return "主胜"
    if actual == "D":
        return "平局"
    return "客胜"


def _check_1x2(pred: dict, actual: str) -> tuple[str, bool]:
    m = pred.get("model", {})
    probs = [m.get("home_win", 0), m.get("draw", 0), m.get("away_win", 0)]
    pick = ["主胜", "平局", "客胜"][max(range(3), key=lambda i: probs[i])]
    labels = {"H": "主胜", "D": "平局", "A": "客胜"}
    return f"胜平负: 预测{pick} → 实际{labels[actual]}", pick == labels[actual]


def _check_ou(pred: dict, goals: int) -> tuple[str, bool] | None:
    ou_v = pred.get("ou_value")
    if not ou_v:
        return None
    over = goals > 2.5
    pick_over = ou_v["side"] == "大2.5"
    actual_txt = "大球" if over else "小球"
    return f"大小球: 模型倾向{ou_v['side']} → 实际{actual_txt}", pick_over == over


def _check_ah(pred: dict, result: dict) -> tuple[str, bool] | None:
    ah = pred.get("ah_handicap") or {}
    e = ah.get("edge") or {}
    if not e.get("best_pick"):
        return None
    gl = ah.get("goal_line", 0)
    hg, ag = result.get("home_goals") or 0, result.get("away_goals") or 0
    # 让球线: 主队让/受让 (负值=主让, 正值=主受)
    margin = (hg - ag) + gl
    if margin > 0:
        cover = "home"
    elif margin == 0:
        cover = "push"
    else:
        cover = "away"
    pick = e["best_pick"]
    if cover == "push":
        # 走盘 = 退款, 不算命中也不算错 (中性)
        return f"让球盘: 模型倾向{pick} → 实际走盘(退款)", None
    ok = pick == cover
    txt = f"让球盘: 模型倾向{pick} → 实际{'主赢盘' if cover == 'home' else '客赢盘'}"
    return txt, ok


def _check_htft(pred: dict, result: dict) -> tuple[str, bool] | None:
    ht = pred.get("ht_ft_odds") or {}
    if not ht:
        return None
    top = sorted(ht.items(), key=lambda x: x[1])[0]
    # 赛果只有全场, 无法验证半全场 → 只列不判 (中性)
    return f"半全场: 最低赔 {top[0]} @ {top[1]:.2f} (无半场比分数据, 无法验证)", None


def generate_review_analysis(date_str: str, matched: list[dict], output_dir: str = "data/output") -> str:
    """生成复盘分析页 (预测vs结果 + LLM错因归因), 返回文件路径"""
    predictions = _load_json(os.path.join(output_dir, f"predictions_{date_str}.json")) or []
    results = _load_json(os.path.join(output_dir, f"results_{date_str}.json")) or []
    drift_map = _load_drift(date_str)

    n_hit = 0
    n_total = 0
    cards = []
    for m in matched:
        home = m.get("home_team", "?")
        away = m.get("away_team", "?")
        key = (home, away)
        pred = next((p for p in predictions
                     if (p.get("home_team") == home and p.get("away_team") == away)
                     or (p.get("home_team") == away and p.get("away_team") == home)), None)
        result = {"home_goals": m.get("home_goals"), "away_goals": m.get("away_goals"), "result": m.get("actual")}
        drift_txt = drift_map.get(key, "")

        rows = []
        hit_count = 0
        # 逐条对照 (有数据才列)
        # 无信号场次 (无赔率冷启动): 不预测不打分
        if pred and pred.get("no_signal"):
            rows.append(("胜平负: 无信号场次 (无赔率冷启动), 未预测", None))
        else:
            chk1 = _check_1x2(pred or m, m.get("actual", ""))
            rows.append((chk1[0], chk1[1]))
            chk_ou = _check_ou(pred or {}, (m.get("home_goals") or 0) + (m.get("away_goals") or 0))
            if chk_ou:
                rows.append(chk_ou)
            chk_ah = _check_ah(pred or {}, result)
            if chk_ah:
                rows.append(chk_ah)
            chk_ht = _check_htft(pred or {}, result)
            if chk_ht:
                rows.append(chk_ht)
        hit_count = sum(1 for _, ok in rows if ok is True)
        n_hit += hit_count
        n_total += sum(1 for _, ok in rows if ok is not None)

        # LLM 归因
        ai_text = ""
        if pred:
            try:
                ai_text = _query_postmortem(_build_postmortem_prompt(pred, result, drift_txt))
                print(f"  [复盘LLM] {home} vs {away}: {len(ai_text)} 字")
            except Exception as e:
                ai_text = "[复盘归因生成失败: " + str(e) + "]"
        parts = _split_ai(ai_text)

        def _row_cell(ok):
            if ok is None:
                return '<td class="na" style="color:#8d99b0;">—</td>'
            return f'<td class="{"hit" if ok else "miss"}">{"✅" if ok else "❌"}</td>'
        rows_html = "".join(
            f"<tr>{_row_cell(ok)}<td>{_esc(txt)}</td></tr>"
            for txt, ok in rows
        )
        drift_html = f'<div class="drift">📈 全天赔率变动\n{_esc(drift_txt)}</div>' if drift_txt else ""
        ai_html = ""
        if ai_text:
            segs = []
            for label, key in (("结果对照", "对照"), ("错因归因", "归因"), ("教训", "教训")):
                if parts.get(key):
                    segs.append(f"<b>{label}:</b> {_esc(parts[key])}")
            ai_html = f'<div class="ai">🤖 赛后归因 (LLM)\n{"\n".join(segs)}</div>'
        cards.append(f"""
<article class="match">
  <header class="m-head">
    <div class="m-teams">{_esc(home)} <span class="tvs" style="color:#8d99b0;">VS</span> {_esc(away)}</div>
    <div class="m-score">{m.get("home_goals", "?")} - {m.get("away_goals", "?")}</div>
  </header>
  <table>
    <tr><th style="width:36px;"></th><th>预测对照</th></tr>
    {rows_html}
  </table>
  {drift_html}
  {ai_html}
</article>""")

    total_matches = len(matched)
    summary = f"""
  <div class="summary">
    <div class="s-box"><div class="v">{total_matches}</div><div class="l">复盘场次</div></div>
    <div class="s-box"><div class="v hit">{n_hit}/{n_total}</div><div class="l">预测命中</div></div>
    <div class="s-box"><div class="v miss">{n_total - n_hit}</div><div class="l">未命中</div></div>
    <div class="s-box"><div class="v">{n_hit / n_total:.0%}</div><div class="l">命中率</div></div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>复盘分析 — {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="badge">📋 复盘分析 · 预测vs结果 + 错因归因</div>
    <h1>{date_str}</h1>
    <div class="hero-sub">每条预测逐一对账 · 错在哪、为什么错 · 数据台账见 <a href="review_{date_str}.html">review_{date_str}.html</a></div>
  </div>
  {summary}
  {''.join(cards)}
  <div class="footer">自动生成 · 复盘分析 → 数据台账 双页存档 · <a href="../index.html">返回首页</a></div>
</div>
</body>
</html>"""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"review_analysis_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[复盘分析] 已保存 → {out_path}")
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python pipeline/review_analysis.py <日期YYYY-MM-DD>")
        sys.exit(1)
    date_str = sys.argv[1]
    pred_path = os.path.join("data", "output", f"predictions_{date_str}.json")
    results_path = os.path.join("data", "output", f"results_{date_str}.json")
    if not os.path.exists(pred_path) or not os.path.exists(results_path):
        print("缺少预测或赛果文件, 无法复盘")
        sys.exit(1)
    from pipeline.result_fetcher import match_predictions_to_results
    preds = json.load(open(pred_path, encoding="utf-8"))
    res = json.load(open(results_path, encoding="utf-8"))
    matched = match_predictions_to_results(preds, res)
    generate_review_analysis(date_str, matched)


if __name__ == "__main__":
    main()
