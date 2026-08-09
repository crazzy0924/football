"""Generate standalone prediction HTML for Aug 9."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('data/output/predictions_2026-08-09.json', 'r', encoding='utf-8') as f:
    preds = json.load(f)

LEAGUE_NAMES = {
    'J1': '日职联', 'J2': '日乙', 'DED': '荷甲', 'BL2': '德乙',
    'SWE': '瑞典超', 'FIN': '芬超', 'NOR': '挪超', 'PPL': '葡超',
    'BSA': '巴甲',
}

def get_pick(hp, dp, ap):
    if hp > max(dp, ap): return '主胜', 'home'
    elif ap > max(hp, dp): return '客胜', 'away'
    return '平局', 'draw'

rows = []
for i, p in enumerate(preds):
    h = p['home_team']
    a = p['away_team']
    h_cn = p.get('home_cn', h)
    a_cn = p.get('away_cn', a)
    lg = p['league_code']
    lg_cn = LEAGUE_NAMES.get(lg, lg)
    cs = p.get('cold_start', False)
    m = p.get('model', {})
    hp = m.get('home_win', 0)
    dp = m.get('draw', 0)
    ap = m.get('away_win', 0)
    pick, pick_class = get_pick(hp, dp, ap)
    elo_h = p.get('elo_home', 1500)
    elo_a = p.get('elo_away', 1500)

    bh = bd = ba = 0
    bayes = p.get('bayesian')
    if bayes and isinstance(bayes, dict):
        bp = bayes.get('posterior', {})
        if bp and isinstance(bp, dict):
            bh = bp.get('home', 0)
            bd = bp.get('draw', 0)
            ba = bp.get('away', 0)

    edge_h = edge_a = 0
    odds = p.get('value', {})
    if odds and isinstance(odds, dict):
        edge_h = odds.get('edge_home', 0) or 0
        edge_a = odds.get('edge_away', 0) or 0
    has_odds = bool(odds and odds.get('has_odds', True) and (bh + bd + ba) > 0)

    rows.append({
        'num': i + 1, 'h': h, 'a': a, 'h_cn': h_cn, 'a_cn': a_cn,
        'lg': lg_cn, 'cs': cs, 'hp': hp, 'dp': dp, 'ap': ap,
        'pick': pick, 'pick_class': pick_class,
        'elo_h': elo_h, 'elo_a': elo_a,
        'bh': bh, 'bd': bd, 'ba': ba,
        'edge_h': edge_h, 'edge_a': edge_a,
        'has_odds': has_odds,
        'match_num': p.get('match_num', ''),
    })

# ---- HTML ----
html = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JOYBOY · 8月9日终盘预测 · v3.0</title>
<style>
:root {
  --bg: #09090d; --card: #111118; --border: #1c1c2a;
  --text: #d0d0dc; --muted: #6b6b80;
  --accent: #f0a838; --green: #3fb950; --red: #f85149;
  --blue: #58a6ff; --cyan: #00d4ff; --pink: #ff6b9d; --purple: #a78bfa;
}
* { margin:0; padding:0; box-sizing:border-box }
body {
  font-family: 'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;
  background: var(--bg); color: var(--text); font-size: 14px; line-height:1.6;
  min-height: 100vh;
}
.layout { display:flex; min-height:100vh; max-width:1380px; margin:0 auto; }
/* LEFT BRAND */
.left {
  width: 120px; min-width: 120px;
  background: linear-gradient(180deg, #050510 0%, #0c0c20 40%, #080818 60%, #050510 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-right: 1px solid #1a1a2e; position: relative; flex-shrink: 0;
}
.left::before {
  content: ''; position: absolute; top: 15%; left: 0; right: 0; height: 70%;
  background: radial-gradient(ellipse at center, rgba(0,212,255,0.04) 0%, transparent 60%);
  pointer-events: none;
}
.jb { display: flex; flex-direction: column; align-items: center; gap: 3px; z-index: 1; }
.jb span {
  font-family: 'Georgia','Palatino',serif; font-size: 2.6em; font-weight: 900; line-height: 0.95;
  background: linear-gradient(180deg, #00d4ff 0%, #a78bfa 30%, #ff6b9d 55%, #f0a838 80%, #00d4ff 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.jb .tag {
  font-size: 0.45em; color: var(--muted); font-family: 'PingFang SC','Microsoft YaHei',sans-serif;
  letter-spacing: 6px; font-weight: 300; writing-mode: vertical-rl; margin-top: 8px; opacity: 0.4;
}
/* MAIN */
.main { flex: 1; padding: 22px 26px; overflow-y: auto; }
h1 { font-size: 1.1em; font-weight: 800; margin-bottom: 2px; letter-spacing: -0.2px; }
h1 em { color: var(--accent); font-style: normal; }
.sub { font-size: 0.6em; color: var(--muted); margin-bottom: 14px; }
/* STATS */
.stats { display: flex; gap: 7px; margin-bottom: 16px; flex-wrap: wrap; }
.st { flex: 1; min-width: 60px; background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 7px; text-align: center; }
.st:hover { border-color: #2a2a3e; }
.st .n { font-size: 1.35em; font-weight: 800; }
.st .l { font-size: 0.55em; color: var(--muted); margin-top: 3px; }
/* TABLE */
.table-wrap { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--card); }
table { width: 100%; border-collapse: collapse; }
thead th {
  background: #0d0d1a; color: var(--muted); font-size: 0.63em; font-weight: 600;
  text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border);
  letter-spacing: 0.5px; text-transform: uppercase;
}
thead th.r { text-align: right; }
thead th.c { text-align: center; }
tbody td { padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,0.02); font-size: 0.83em; vertical-align: middle; }
tbody tr:hover { background: rgba(255,255,255,0.015); }
tbody tr.cold-row { background: rgba(167,139,250,0.03); }
.num { color: var(--muted); font-size: 0.68em; min-width: 28px; }
.teams { font-weight: 600; }
.teams .cn { font-size: 0.68em; color: var(--muted); font-weight: 400; margin-top: 1px; }
.league { font-size: 0.63em; color: var(--muted); background: rgba(255,255,255,0.03); padding: 2px 6px; border-radius: 4px; white-space: nowrap; }
.bar-wrap { display: flex; height: 5px; border-radius: 3px; overflow: hidden; background: rgba(255,255,255,0.04); min-width: 130px; gap: 1px; }
.bar-h { background: var(--blue); border-radius: 3px 0 0 3px; }
.bar-d { background: #555; }
.bar-a { background: var(--accent); border-radius: 0 3px 3px 0; }
.prob-pct { font-weight: 600; font-size: 0.8em; }
.prob-pct.h { color: var(--blue); } .prob-pct.d { color: #888; } .prob-pct.a { color: var(--accent); }
.pick { display: inline-block; padding: 2px 9px; border-radius: 5px; font-size: 0.7em; font-weight: 700; }
.pick.home { background: rgba(58,130,246,0.15); color: var(--blue); }
.pick.away { background: rgba(240,168,56,0.15); color: var(--accent); }
.pick.draw { background: rgba(139,143,163,0.12); color: var(--muted); }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.58em; font-weight: 600; white-space: nowrap; }
.badge.trained { background: rgba(63,185,80,0.1); color: var(--green); }
.badge.cold { background: rgba(167,139,250,0.12); color: var(--purple); }
.badge.no-odds { background: rgba(248,81,73,0.1); color: var(--red); }
.elo { font-size: 0.72em; color: var(--muted); }
/* LEGEND */
.legend { display: flex; gap: 14px; margin: 12px 0 6px; font-size: 0.58em; color: var(--muted); flex-wrap: wrap; }
.legend span { display: flex; align-items: center; gap: 4px; }
.legend .dot { width: 8px; height: 8px; border-radius: 2px; }
.ft { text-align: center; padding: 20px; color: var(--muted); font-size: 0.48em; opacity: 0.3; }

@media (max-width: 768px) {
  .layout { flex-direction: column; max-width: 100%; }
  .left { width: 100%; min-width: 0; flex-direction: row; padding: 8px 14px; border-right: none; border-bottom: 1px solid #1a1a2e; }
  .jb { flex-direction: row; gap: 5px; }
  .jb span { font-size: 1.1em; }
  .jb .tag { writing-mode: horizontal-tb; letter-spacing: 2px; margin-top: 0; font-size: 0.5em; }
  .main { padding: 10px 6px; }
  .bar-wrap { min-width: 60px; }
  table { font-size: 0.72em; }
  thead th, tbody td { padding: 6px 5px; }
}
@media print {
  .left { display: none; }
  body { background: white; color: #111; }
}
</style>
</head>
<body>
<div class="layout">

<div class="left">
  <div class="jb">
    <span>J</span><span>O</span><span>Y</span><span>B</span><span>O</span><span>Y</span>
    <div class="tag">足球预测</div>
  </div>
</div>

<div class="main">
<h1>⚽ <em>终盘预测报告</em> · 2026年8月9日 周日</h1>
<p class="sub">v3.0 Dixon-Coles · 贝叶斯融合 · 训练集 26,663 场 / 662 队 · 24 联赛覆盖 · 队名匹配已修复</p>

<div class="stats">
  <div class="st"><div class="n" style="color:var(--green)">20/24</div><div class="l">训练覆盖</div></div>
  <div class="st"><div class="n" style="color:var(--purple)">4</div><div class="l">冷启动</div></div>
  <div class="st"><div class="n" style="color:var(--blue)">14</div><div class="l">主胜推荐</div></div>
  <div class="st"><div class="n" style="color:var(--accent)">10</div><div class="l">客胜推荐</div></div>
  <div class="st"><div class="n" style="color:var(--muted)">26663</div><div class="l">训练场次</div></div>
  <div class="st"><div class="n" style="color:var(--cyan)">662</div><div class="l">训练球队</div></div>
  <div class="st"><div class="n" style="color:var(--green)">83%</div><div class="l">覆盖率</div></div>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
  <th>#</th>
  <th>比赛</th>
  <th>联赛</th>
  <th class="c" style="width:22%">概率分布</th>
  <th class="c">推荐</th>
  <th class="c">贝叶斯后验</th>
  <th class="c">训练</th>
  <th class="r">ELO差</th>
</tr>
</thead>
<tbody>
'''

for r in rows:
    h_bar = int(r['hp'] * 100)
    d_bar = int(r['dp'] * 100)
    a_bar = int(r['ap'] * 100)
    elo_diff = round(r['elo_h'] - r['elo_a'])
    elo_sign = '+' if elo_diff > 0 else ''

    has_bayes = r['bh'] + r['bd'] + r['ba'] > 0.001
    bayes_str = f"{r['bh']:.1%}/{r['bd']:.1%}/{r['ba']:.1%}" if has_bayes else '—'

    cold_cls = ' cold-row' if r['cs'] else ''
    cs_label = '❄️ 冷启动' if r['cs'] else '✅ 训练'
    cs_class = 'cold' if r['cs'] else 'trained'

    no_odds_badge = ' <span class="badge no-odds">无赔率</span>' if not r['has_odds'] else ''

    html += f'''<tr{cold_cls}>
  <td class="num">{r['num']:02d}</td>
  <td>
    <div class="teams">{r['h']} <span style="color:var(--muted);font-weight:400">vs</span> {r['a']}
    <span class="cn">{r['h_cn']} vs {r['a_cn']}</span></div>
  </td>
  <td><span class="league">{r['lg']}</span></td>
  <td>
    <div class="bar-wrap">
      <div class="bar-h" style="width:{h_bar}%"></div>
      <div class="bar-d" style="width:{d_bar}%"></div>
      <div class="bar-a" style="width:{a_bar}%"></div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:2px;font-size:0.7em">
      <span class="prob-pct h">主 {r['hp']:.1%}</span>
      <span class="prob-pct d">平 {r['dp']:.1%}</span>
      <span class="prob-pct a">客 {r['ap']:.1%}</span>
    </div>
  </td>
  <td style="text-align:center"><span class="pick {r['pick_class']}">{r['pick']}</span></td>
  <td style="text-align:center;font-size:0.76em;color:var(--text-dim)">{bayes_str}</td>
  <td style="text-align:center">
    <span class="badge {cs_class}">{cs_label}</span>{no_odds_badge}
  </td>
  <td class="elo" style="text-align:right">{elo_sign}{elo_diff}</td>
</tr>
'''

html += '''</tbody>
</table>
</div>

<div class="legend">
  <span><span class="dot" style="background:var(--blue)"></span> 主胜</span>
  <span><span class="dot" style="background:#555"></span> 平局</span>
  <span><span class="dot" style="background:var(--accent)"></span> 客胜</span>
  <span style="margin-left:8px">✅ 训练 = 有历史攻防参数</span>
  <span>❄️ 冷启动 = 新队/无数据，使用联赛均值</span>
  <span style="margin-left:8px;color:var(--red)">⚠ 体彩无SPF赔率，贝叶斯融合跳过</span>
</div>

<div class="ft">JOYBOY · Football Prediction Engine · v3.0 Dixon-Coles · 2026-08-09 · github.com/crazzy0924/football</div>

</div>
</div>
</body>
</html>'''

with open('predictions_20260809.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'OK: predictions_20260809.html ({len(html):,} bytes, {len(rows)} matches)')
