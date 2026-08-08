#!/usr/bin/env python3
"""午盘分析 JSON → HTML"""
import json, sys, io
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except: pass

ROOT = Path(__file__).resolve().parent

def generate(tracking_path, output_path):
    data = json.loads(open(tracking_path, encoding='utf-8').read())
    signals = data.get('afternoon_signals', [])
    date_str = data.get('date', '')

    rows = ""
    for m in data['matches']:
        mid = m['match_id']
        alerts = m.get('afternoon_alerts', [])
        chg = m.get('afternoon_spf_changes', {})
        old_spf = m.get('official_spf') or {}
        new_spf = m.get('official_spf') or {}
        old_h = old_spf.get('h', '-')

        cls = ' class="hot"' if alerts else ''
        alert_html = '<br>'.join(alerts) if alerts else '-'

        rows += f"""<tr{cls}>
          <td>{mid}</td>
          <td>{m['home_team_cn']} vs {m['away_team_cn']}</td>
          <td>{m['league_cn']}</td>
          <td>{old_spf.get('h','-')}/{old_spf.get('d','-')}/{old_spf.get('a','-')}</td>
          <td>{new_spf.get('h','-')}/{new_spf.get('d','-')}/{new_spf.get('a','-')}</td>
          <td>{chg.get('home','-')}%/{chg.get('draw','-')}%/{chg.get('away','-')}%</td>
          <td>{alert_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>午盘分析 · {date_str}</title>
<style>
:root{{--bg:#09090d;--card:#111118;--border:#1c1c2a;--text:#c8c8d4;--muted:#5a5a6e;
  --accent:#f0a838;--green:#3fb950;--red:#f85149;--blue:#58a6ff;--cyan:#00d4ff;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.6;min-height:100vh;padding:24px;max-width:1300px;margin:0 auto}}
h1{{font-size:1.3em;font-weight:800;margin-bottom:4px}}h1 em{{color:var(--accent);font-style:normal}}
.sub{{font-size:0.7em;color:var(--muted);margin-bottom:16px}}
.stats{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.st{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;text-align:center}}
.st .n{{font-size:1.3em;font-weight:800}}.st .l{{font-size:0.56em;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:0.82em}}
th{{background:var(--card);padding:8px 6px;text-align:left;font-size:0.7em;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);position:sticky;top:0;z-index:1}}
td{{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,0.03);vertical-align:top}}
tr:hover td{{background:rgba(255,255,255,0.015)}}
tr.hot td{{background:rgba(255,107,157,0.05)}}
.signal-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:16px}}
.signal-box h2{{font-size:0.95em;margin-bottom:8px}}
.signal-item{{padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03)}}
.signal-item:last-child{{border-bottom:none}}
.tag{{display:inline-block;padding:1px 5px;border-radius:4px;font-size:0.6em;font-weight:600;margin-right:4px}}
.tp{{background:rgba(63,185,80,0.1);color:var(--green)}}
.tr{{background:rgba(248,81,73,0.1);color:var(--red)}}
.tb{{background:rgba(88,166,255,0.1);color:var(--blue)}}
.note{{font-size:0.65em;color:var(--muted);margin-top:16px;padding:10px;background:var(--card);border-radius:6px;border:1px solid var(--border)}}
</style>
</head>
<body>
<h1>📊 <em>午盘分析</em> · {date_str}</h1>
<p class="sub">体彩官方SPF实时赔率对比 · 蒸汽移动检测 · 资金流向追踪</p>

<div class="stats">
  <div class="st"><div class="n">{data['total_matches']}</div><div class="l">总场次</div></div>
  <div class="st"><div class="n" style="color:var(--red)">{len(signals)}</div><div class="l">出现信号</div></div>
  <div class="st"><div class="n">{data.get('afternoon_analysis',{}).get('api_data_available','?')}</div><div class="l">API可用</div></div>
</div>

<div class="signal-box">
<h2>⚠ 午盘关键信号</h2>
{''.join(f'<div class="signal-item"><span class="tag tr">★</span> <strong>{s["match_id"]} {s["home"]} vs {s["away"]} ({s["league"]})</strong><br><span style="font-size:0.8em">早盘{s["old_spf"]} → 午盘{s["new_spf"]}<br>{" | ".join(s["alerts"])}</span></div>' for s in signals) if signals else '<p style="color:var(--muted)">所有比赛赔率稳定，无异常信号</p>'}
</div>

<table>
<thead><tr>
<th>编号</th><th>比赛</th><th>联赛</th><th>早盘SPF</th><th>午盘SPF</th><th>概率变化</th><th>信号</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>

<div class="note">
<strong>📐 方法:</strong> 对比体彩官方SPF赔率早盘(09:00) vs 午盘(16:00) · 蒸汽移动=赔率骤降>8% · 亚盘盘口变化=庄家态度转变<br>
<strong>⚠ 004全北现代:</strong> 客胜赔率从4.65→4.05, 骤降15%, 资金大量涌入客队, 早场终盘推荐的主胜需重新评估<br>
<strong>生成时间:</strong> {datetime.now().isoformat()}
</div>
</body>
</html>"""

    Path(output_path).write_text(html, encoding='utf-8')
    print(f"HTML saved: {output_path}")


if __name__ == '__main__':
    generate(
        ROOT / 'daily_tracking.json',
        ROOT / 'afternoon_20260808.html'
    )
