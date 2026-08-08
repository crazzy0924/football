#!/usr/bin/env python3
"""
体彩预测JSON → HTML报告生成器
用法: python generate_lottery_html.py data/lottery_predictions_2026-08-09_1512.json
"""
import json, sys
from datetime import datetime
from pathlib import Path

def _fmt_pct(v): return f"{v:.0%}" if isinstance(v, float) else str(v)

def generate_html(json_path: str, output_path: str = None, title: str = "体彩预测"):
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    date_str = data.get("date", "")
    results = data.get("results", [])

    matches_html = ""
    for r in results:
        ln = r["lottery"]["matchNum"]
        f = r["final"]
        fp = f["final_prediction"]
        m = r.get("market", {})
        rv = r["reviewer"]
        ctx_league = r.get("league", "?")
        ctx_code = r.get("league_code", "?")
        odds_src = (r.get("market") or {}).get("raw_odds", {})

        # 置信颜色
        conf_color = {"高": "#3fb950", "中": "#f0a838", "低": "#f85149"}.get(
            f.get("final_confidence", "低"), "#f85149")

        # 方向icon
        dir_icon = {"主胜": "🏠", "平局": "🤝", "客胜": "✈️"}.get(fp["direction"], "❓")

        # 赔率
        if odds_src:
            odds_str = f'{odds_src.get("home","?")}/{odds_src.get("draw","?")}/{odds_src.get("away","?")}'
        else:
            odds_str = "-"

        # 让球 (from context, not directly in result)
        hhad = {}
        hhad_str = ""
        if hhad:
            gl = hhad.get("goal_line", "")
            if gl:
                hhad_str = f'让球{gl} | {hhad.get("home","?")}/{hhad.get("draw","?")}/{hhad.get("away","?")}'

        # 警告
        warns = f.get("warnings", [])
        warn_html = "".join(f'<span class="warn">{w}</span> ' for w in warns[:3])

        # Reviewer
        rv_icon = {"agree": "✅", "agree_with_reservation": "⚠️", "disagree": "🔴"}.get(
            rv.get("verdict", ""), "❓")

        matches_html += f"""
        <tr>
          <td class="num">{ln}</td>
          <td class="teams">
            <div class="match-name">{r['match']}</div>
            <div class="league-tag">{ctx_league} · {ctx_code}</div>
          </td>
          <td class="odds">{odds_str}<br><small>{hhad_str}</small></td>
          <td class="dir">{dir_icon} {fp['direction']}</td>
          <td class="conf" style="color:{conf_color}">{f.get('final_confidence','?')}</td>
          <td class="probs">
            主{fp['home_win']:.0%}<br>平{fp['draw']:.0%}<br>客{fp['away_win']:.0%}
          </td>
          <td class="eg">{fp['expected_goals']}</td>
          <td class="sub">
            {fp.get('over_25_direction','?')}<br>
            {fp.get('btts_direction','?')}<br>
            <small>波胆:{fp.get('most_likely_score','?')}</small>
          </td>
          <td class="rv">{rv_icon} {rv.get('verdict','?')}</td>
          <td class="warnings">{warn_html}</td>
        </tr>"""

    # 统计
    agrees = sum(1 for r in results if r["reviewer"].get("verdict") == "agree")
    bets = sum(1 for r in results if r["final"]["bet_suggestion"].get("type") != "none")
    dirs = {}
    for r in results:
        d = r["final"]["final_prediction"]["direction"]
        dirs[d] = dirs.get(d, 0) + 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 体彩竞彩 · {date_str}</title>
<style>
:root{{--bg:#09090d;--card:#111118;--border:#1c1c2a;--text:#c8c8d4;--muted:#5a5a6e;
  --accent:#f0a838;--green:#3fb950;--red:#f85149;--blue:#58a6ff;--cyan:#00d4ff;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.6;min-height:100vh;padding:24px;max-width:1400px;margin:0 auto}}
h1{{font-size:1.3em;font-weight:800;margin-bottom:4px}}
h1 em{{color:var(--accent);font-style:normal}}
.sub{{font-size:0.7em;color:var(--muted);margin-bottom:16px}}
.stats{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.st{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;text-align:center}}
.st .n{{font-size:1.3em;font-weight:800}}.st .l{{font-size:0.56em;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:0.82em}}
th{{background:var(--card);padding:8px 6px;text-align:left;font-size:0.7em;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);position:sticky;top:0;z-index:1}}
td{{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,0.03);vertical-align:top}}
tr:hover td{{background:rgba(255,255,255,0.015)}}
.num{{font-weight:700;color:var(--muted);min-width:55px}}
.match-name{{font-weight:600}}
.league-tag{{font-size:0.65em;color:var(--muted)}}
.odds{{font-weight:600;min-width:80px}}
.odds small{{color:var(--muted);font-weight:400}}
.dir{{font-weight:700;min-width:60px}}
.conf{{font-weight:800;min-width:36px}}
.probs{{font-size:0.75em;color:var(--muted);min-width:50px}}
.eg{{font-weight:600;color:var(--cyan);min-width:30px}}
.sub{{font-size:0.75em;min-width:70px}}
.sub small{{color:var(--muted)}}
.rv{{font-size:0.75em;min-width:90px}}
.warnings{{font-size:0.65em;max-width:280px}}
.warn{{display:inline-block;background:rgba(248,81,73,0.08);color:var(--red);padding:1px 4px;border-radius:3px;margin:1px 0}}
.note{{font-size:0.65em;color:var(--muted);margin-top:16px;padding:10px;background:var(--card);border-radius:6px;border:1px solid var(--border)}}
</style>
</head>
<body>
<h1>⚽ <em>体彩竞彩预测</em> · {date_str}</h1>
<p class="sub">LLM Actor-Reviewer双人共识 · 体彩官方SPF赔率 · 24场六维预测</p>

<div class="stats">
  <div class="st"><div class="n">{len(results)}</div><div class="l">总场次</div></div>
  <div class="st"><div class="n" style="color:var(--green)">{bets}</div><div class="l">推荐投注</div></div>
  <div class="st"><div class="n" style="color:var(--blue)">{agrees}</div><div class="l">双审一致</div></div>
  <div class="st"><div class="n">{dirs.get('主胜',0)}</div><div class="l">主胜方向</div></div>
  <div class="st"><div class="n">{dirs.get('平局',0)}</div><div class="l">平局方向</div></div>
  <div class="st"><div class="n">{dirs.get('客胜',0)}</div><div class="l">客胜方向</div></div>
  <div class="st"><div class="n">{data.get('kambi_matched', 0)}</div><div class="l">Kambi补充</div></div>
</div>

<table>
<thead>
<tr>
  <th>编号</th><th>比赛</th><th>赔率(SPF)</th><th>方向</th><th>置信</th>
  <th>概率</th><th>进球</th><th>大小/BTTS/波胆</th><th>审核</th><th>风险提示</th>
</tr>
</thead>
<tbody>
{matches_html}
</tbody>
</table>

<div class="note">
  <strong>⚙️ 管线:</strong> 体彩官方SPF赔率 → DeepSeek LLM Actor推理 → LLM Reviewer审核 → 规则引擎 |
  <strong>数据:</strong> {date_str} 体彩竞彩24场 |
  <strong>生成时间:</strong> {data.get('generated_at', datetime.now().isoformat())} |
  <strong>⚠ 注意:</strong> 所有预测置信度为"低"因ELO数据为联赛默认值，市场赔率为主要信号。仅供参考，不构成投注建议。
</div>
</body>
</html>"""

    if output_path is None:
        output_path = json_path.replace(".json", ".html")
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"HTML已生成: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python generate_lottery_html.py <predictions.json> [output.html]")
        sys.exit(1)
    generate_html(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
