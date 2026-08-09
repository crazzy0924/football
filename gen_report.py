"""生成七维预测报告 + 模拟下注 (当前可用四维: 胜平负/让球/大小球/波胆)"""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── 加载五维数据 ──────────────────────────────────
five_dim_path = Path('data/output/five_dim_2026-08-09.json')
if not five_dim_path.exists():
    print("请先运行: python pipeline/five_dim_predictor.py")
    sys.exit(1)

with open(five_dim_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# ── 联赛中文 ──────────────────────────────────────
LEAGUE_CN = {
    'J1': '日职联', 'J2': '日乙', 'DED': '荷甲', 'BL2': '德乙',
    'SWE': '瑞典超', 'FIN': '芬超', 'NOR': '挪超', 'PPL': '葡超',
    'BSA': '巴甲',
}

BANKROLL = 10000
KELLY_FRACTION = 0.25

# ── 下注决策 ──────────────────────────────────────
def decide_bets(data):
    """综合四维决定下注"""
    bets = []
    for d in data:
        cs = d['cold_start']
        bet_lines = []

        # 维度1: 胜平负
        v = d.get('value')
        if v and v.get('kelly', 0) > 0:
            kelly = v['kelly']
            kf = kelly * KELLY_FRACTION
            if cs:
                kf = min(kf, 0.02)
            if kf >= 0.0025:
                direction = v.get('best_direction', '')
                dir_cn = {'home': '主胜', 'away': '客胜', 'draw': '平局'}.get(direction, direction)
                stake = int(BANKROLL * kf)
                odds_data = d['dim_1x2'].get('market_odds', {})
                odds_val = float(odds_data.get(direction[0], 0)) if odds_data else 0
                bet_lines.append({
                    'dim': '胜平负', 'direction': dir_cn, 'kelly': kelly,
                    'stake': stake, 'odds': odds_val, 'edge': v.get(f'{direction}_edge', 0),
                })

        # 维度2: 让球
        ha = d['dim_handicap']['analysis']
        if ha.get('kelly', 0) > 0.008:
            kf = ha['kelly'] * KELLY_FRACTION
            if cs:
                kf = min(kf, 0.02)
            if kf >= 0.005:
                bp = ha['best_pick']
                bp_cn = {'home': '主队', 'push': '平局', 'away': '客队'}.get(bp, bp)
                stake = int(BANKROLL * kf)
                odds_data = d['dim_handicap'].get('market_odds', {})
                odds_val = float(odds_data.get(bp[0], 0)) if odds_data else 0
                gl = d['dim_handicap']['goal_line']
                bet_lines.append({
                    'dim': f'让球({gl:+.0f})', 'direction': bp_cn, 'kelly': ha['kelly'],
                    'stake': stake, 'odds': odds_val, 'edge': ha['edge'],
                })

        # 维度3: 大小球
        ta = d['dim_totals']['analysis']
        if ta.get('kelly', 0) > 0.008:
            kf = ta['kelly'] * KELLY_FRACTION
            if cs:
                kf = min(kf, 0.02)
            if kf >= 0.005:
                bp = ta['best_pick']
                bp_cn = {'over_2_5': '大2.5', 'over_3_5': '大3.5'}.get(bp, bp)
                stake = int(BANKROLL * kf)
                bet_lines.append({
                    'dim': '大小球', 'direction': bp_cn, 'kelly': ta['kelly'],
                    'stake': stake, 'odds': 1.85, 'edge': ta['edge'],
                })

        bets.append({
            'match': f"{d['home_cn']} vs {d['away_cn']}",
            'match_num': d.get('match_num', ''),
            'league': LEAGUE_CN.get(d['league_code'], d['league_code']),
            'cold_start': cs,
            'lines': bet_lines,
        })
    return bets


bets = decide_bets(data)
total_stakes = sum(sum(line['stake'] for line in b['lines']) for b in bets)
total_lines = sum(len(b['lines']) for b in bets)
bet_matches = sum(1 for b in bets if b['lines'])

# ── HTML ──────────────────────────────────────────
html = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JOYBOY · 8月9日 多维预测 · v3.0</title>
<style>
:root {
  --bg: #09090d; --card: #111118; --border: #1c1c2a;
  --text: #d0d0dc; --muted: #6b6b80;
  --accent: #f0a838; --green: #3fb950; --red: #f85149;
  --blue: #58a6ff; --cyan: #00d4ff; --purple: #a78bfa;
}
* { margin:0; padding:0; box-sizing:border-box }
body {
  font-family: 'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;
  background: var(--bg); color: var(--text); font-size: 14px; line-height:1.6;
  min-height: 100vh;
}
.layout { display:flex; min-height:100vh; max-width:1520px; margin:0 auto; }
.left {
  width: 100px; min-width: 100px;
  background: linear-gradient(180deg, #050510 0%, #0c0c20 40%, #080818 60%, #050510 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-right: 1px solid #1a1a2e; position: relative; flex-shrink: 0;
}
.jb { display: flex; flex-direction: column; align-items: center; gap: 2px; z-index: 1; }
.jb span {
  font-family: 'Georgia',serif; font-size: 2.2em; font-weight: 900; line-height: 0.95;
  background: linear-gradient(180deg, #00d4ff, #a78bfa, #ff6b9d, #f0a838, #00d4ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.jb .tag { font-size: 0.4em; color: var(--muted); letter-spacing: 4px; writing-mode: vertical-rl; margin-top: 6px; opacity: 0.4; }
.main { flex: 1; padding: 20px 24px; overflow-y: auto; }
h1 { font-size: 1.05em; font-weight: 800; }
h1 em { color: var(--accent); font-style: normal; }
.sub { font-size: 0.58em; color: var(--muted); margin-bottom: 12px; }
/* STATS */
.stats { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
.st { flex: 1; min-width: 55px; background: var(--card); border: 1px solid var(--border);
  border-radius: 7px; padding: 8px 6px; text-align: center; }
.st .n { font-size: 1.2em; font-weight: 800; }
.st .l { font-size: 0.52em; color: var(--muted); margin-top: 2px; }
/* MATCH CARD */
.match-card {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 18px; margin-bottom: 12px;
}
.match-card.bet-card { border-left: 3px solid var(--green); }
.match-card.cold-card { background: rgba(167,139,250,0.02); }
.match-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
}
.match-teams { font-size: 1.05em; font-weight: 700; }
.match-league { font-size: 0.6em; color: var(--muted); background: rgba(255,255,255,0.03); padding: 3px 8px; border-radius: 4px; }
/* DIM GRID */
.dim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.dim-box {
  background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04);
  border-radius: 7px; padding: 10px 12px;
}
.dim-box.full { grid-column: 1 / -1; }
.dim-label { font-size: 0.6em; color: var(--muted); font-weight: 600; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
.dim-probs { display: flex; gap: 6px; font-size: 0.85em; font-weight: 600; margin-bottom: 2px; }
.dim-probs .hp { color: var(--blue); } .dim-probs .dp { color: var(--muted); } .dim-probs .ap { color: var(--accent); }
.dim-probs .ov { color: var(--green); } .dim-probs .un { color: var(--red); }
.dim-pick { font-size: 0.7em; font-weight: 700; }
.dim-edge { font-size: 0.65em; }
.dim-edge.pos { color: var(--green); } .dim-edge.neg { color: var(--red); }
.scores-grid { display: flex; flex-wrap: wrap; gap: 4px; }
.score-chip {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);
  border-radius: 4px; padding: 2px 8px; font-size: 0.7em; font-family: monospace;
}
.score-chip.top { border-color: rgba(240,168,56,0.3); color: var(--accent); font-weight: 600; }
.bet-tag { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 0.55em; font-weight: 700; margin-left: 4px; }
.bet-tag.bet { background: rgba(63,185,80,0.2); color: var(--green); }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.55em; font-weight: 600; }
.badge.trained { background: rgba(63,185,80,0.1); color: var(--green); }
.badge.cold { background: rgba(167,139,250,0.12); color: var(--purple); }
.badge.na { background: rgba(248,81,73,0.1); color: var(--red); }
.bet-summary {
  background: linear-gradient(135deg, rgba(63,185,80,0.06), rgba(58,130,246,0.04));
  border: 1px solid rgba(63,185,80,0.2); border-radius: 10px; padding: 12px 16px;
  margin: 14px 0; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.ft { text-align: center; padding: 18px; color: var(--muted); font-size: 0.45em; opacity: 0.3; }
@media (max-width: 768px) {
  .layout { flex-direction: column; }
  .left { width: 100%; min-width: 0; flex-direction: row; padding: 6px 12px; border-right: none; border-bottom: 1px solid #1a1a2e; }
  .jb { flex-direction: row; gap: 4px; }
  .jb span { font-size: 1em; }
  .jb .tag { writing-mode: horizontal-tb; letter-spacing: 2px; margin-top: 0; }
  .dim-grid { grid-template-columns: 1fr; }
  .main { padding: 8px 6px; }
}
</style>
</head>
<body>
<div class="layout">

<div class="left">
  <div class="jb">
    <span>J</span><span>O</span><span>Y</span><span>B</span><span>O</span><span>Y</span>
    <div class="tag">多维预测</div>
  </div>
</div>

<div class="main">
<h1>⚽ <em>多维预测报告</em> · 2026年8月9日 周日</h1>
<p class="sub">v3.0 Dixon-Coles · 四维覆盖: 胜平负/让球(HHAD)/大小球/波胆 · 半场+角球待数据补充 · 训练26663场662队</p>

<div class="stats">
  <div class="st"><div class="n" style="color:var(--green)">20/24</div><div class="l">训练覆盖</div></div>
  <div class="st"><div class="n" style="color:var(--purple)">4</div><div class="l">冷启动</div></div>
  <div class="st"><div class="n" style="color:var(--blue)">4</div><div class="l">预测维度</div></div>
  <div class="st"><div class="n" style="color:var(--green)">''' + str(bet_matches) + '''</div><div class="l">下注场次</div></div>
  <div class="st"><div class="n" style="color:var(--accent)">''' + str(total_lines) + '''</div><div class="l">下注条数</div></div>
  <div class="st"><div class="n" style="color:var(--cyan)">''' + str(total_stakes) + '''</div><div class="l">投注总额</div></div>
  <div class="st"><div class="n" style="color:var(--red)">3</div><div class="l">待补充维度</div></div>
</div>

<div class="bet-summary">
  <div>
    <div style="font-weight:700;color:var(--green);font-size:0.85em">📋 模拟下注规则</div>
    <div style="font-size:0.65em;color:var(--muted);margin-top:3px">
      本金 ¥10,000 · 四分之一凯利 · 冷启动上限2%<br>
      触发: 胜平负Kelly>1% / 让球>0.8% / 大小球>0.8%
    </div>
  </div>
  <div style="margin-left:auto;text-align:right">
    <div style="font-size:0.8em;color:var(--green);font-weight:700">''' + str(bet_matches) + f''' 场 / {total_lines} 注</div>
    <div style="font-size:0.65em;color:var(--muted)">总额 ¥{total_stakes} ({total_stakes/BANKROLL*100:.1f}%仓位)</div>
  </div>
</div>
'''

for d in data:
    cs = d['cold_start']
    card_class = 'bet-card' if any(b['match'].startswith(d['home_cn']) for b in bets if b['lines']) else ''
    if cs:
        card_class += ' cold-card'

    cs_badge = '<span class="badge cold">❄️冷启动</span>' if cs else '<span class="badge trained">✅已训练</span>'

    # 维度1: 胜平负
    x = d['dim_1x2']
    v = d.get('value') or {}
    best_dir = v.get('best_direction', '')
    kelly_1x2 = v.get('kelly', 0) or 0

    # 维度2: 让球
    ha = d['dim_handicap']
    gl = ha['goal_line']
    gl_label = f'让{gl:+.0f}球' if gl != 0 else '平手盘'

    # 维度3: 大小球
    ta = d['dim_totals']

    # 维度4: 波胆
    cs_top = d['dim_correct_score'][:6]

    # 找这场是否有下注
    match_bets = [b for b in bets if b['match'] == f"{d['home_cn']} vs {d['away_cn']}"]
    bet_tags = ''
    if match_bets:
        for bline in match_bets[0]['lines']:
            bet_tags += f' <span class="bet-tag bet">💰{bline["dim"]} {bline["direction"]} ¥{bline["stake"]}</span>'

    html += f'''<div class="match-card {card_class}">
  <div class="match-header">
    <div>
      <span class="match-teams">{d['home_cn']} vs {d['away_cn']}</span>
      {cs_badge}
      {bet_tags}
    </div>
    <span class="match-league">{LEAGUE_CN.get(d['league_code'], d['league_code'])} · {d.get('match_num', '')}</span>
  </div>
  <div class="dim-grid">
    <!-- 胜平负 -->
    <div class="dim-box">
      <div class="dim-label">① 胜平负 (SPF)</div>
      <div class="dim-probs">
        <span class="hp">主 {x['home']:.1%}</span>
        <span class="dp">平 {x['draw']:.1%}</span>
        <span class="ap">客 {x['away']:.1%}</span>
      </div>
'''

    # 市场对比
    if kelly_1x2 > 0.01:
        dir_cn = {'home': '主胜', 'away': '客胜', 'draw': '平局'}.get(best_dir, best_dir)
        edge = v.get(f'{best_dir}_edge', 0)
        ec = 'pos' if edge > 0 else 'neg'
        html += f'      <div class="dim-pick" style="color:var(--green)">→ 投{dir_cn} | 凯利 {kelly_1x2:.1%} | <span class="dim-edge {ec}">优势{edge:+.1%}</span></div>\n'
    elif kelly_1x2 > 0:
        html += f'      <div class="dim-pick" style="color:var(--muted)">凯利 {kelly_1x2:.1%} (不足)</div>\n'
    else:
        html += f'      <div class="dim-pick" style="color:var(--muted)">无模型优势</div>\n'

    html += '''    </div>
    <!-- 让球 -->
    <div class="dim-box">
      <div class="dim-label">② 让球 (HHAD) ''' + gl_label + '''</div>
      <div class="dim-probs">
        <span class="hp">主 {:.1%}</span>
        <span class="dp">走 {:.1%}</span>
        <span class="ap">客 {:.1%}</span>
      </div>
'''.format(ha['home_cover'], ha['push'], ha['away_cover'])

    ha_edge = ha['analysis'].get('edge', 0)
    ha_kelly = ha['analysis'].get('kelly', 0)
    ha_best = ha['analysis'].get('best_pick', '')
    if ha_kelly > 0.008:
        bp_cn = {'home': '主队', 'push': '走水', 'away': '客队'}.get(ha_best, ha_best)
        ec = 'pos' if ha_edge > 0 else 'neg'
        html += f'      <div class="dim-pick" style="color:var(--green)">→ 投{bp_cn} | 凯利 {ha_kelly:.1%} | <span class="dim-edge {ec}">优势{ha_edge:+.1%}</span></div>\n'
    else:
        html += f'      <div class="dim-pick" style="color:var(--muted)">无显著优势</div>\n'

    html += '''    </div>
    <!-- 大小球 -->
    <div class="dim-box">
      <div class="dim-label">③ 大小球 (TTG)</div>
      <div class="dim-probs">
        <span class="ov">大2.5 {:.1%}</span>
        <span class="ov">大3.5 {:.1%}</span>
        <span style="color:var(--muted);font-size:0.7em">预期{:.2f}球</span>
      </div>
'''.format(ta['over_2_5'], ta['over_3_5'], ta['expected_goals'])

    ta_edge = ta['analysis'].get('edge', 0)
    ta_kelly = ta['analysis'].get('kelly', 0)
    ta_best = ta['analysis'].get('best_pick', '')
    if ta_kelly > 0.008:
        bp_cn = {'over_2_5': '大2.5球', 'over_3_5': '大3.5球'}.get(ta_best, ta_best)
        ec = 'pos' if ta_edge > 0 else 'neg'
        html += f'      <div class="dim-pick" style="color:var(--green)">→ 投{bp_cn} | 凯利 {ta_kelly:.1%} | <span class="dim-edge {ec}">优势{ta_edge:+.1%}</span></div>\n'
    else:
        html += f'      <div class="dim-pick" style="color:var(--muted)">无显著优势</div>\n'

    html += '''    </div>
    <!-- 波胆 -->
    <div class="dim-box">
      <div class="dim-label">④ 波胆 (最可能比分)</div>
      <div class="scores-grid">
'''
    for i, s in enumerate(cs_top):
        chip_class = 'top' if i < 3 else ''
        html += f'        <span class="score-chip {chip_class}">{s["score"]} {s["prob"]:.1%}</span>\n'

    html += '''      </div>
    </div>
  </div>
</div>
'''

html += '''
<div style="margin:14px 0;padding:12px 16px;background:var(--card);border:1px solid var(--border);border-radius:8px">
  <div style="font-size:0.75em;color:var(--muted);font-weight:600;margin-bottom:4px">⏳ 待补充维度 (需新数据源)</div>
  <div style="font-size:0.65em;color:var(--muted)">
    ⑤ 半场让球 · ⑥ 半场大小球 → 需半场比分数据训练半场DC模型<br>
    ⑦ 角球 → 需角球数据 + 独立角球模型<br>
    <span style="color:var(--accent)">计划: 搜集历史半场/角球数据后可快速接入现有框架</span>
  </div>
</div>

<div class="ft">JOYBOY · v3.0 Multi-Dim Predictor · Dixon-Coles Engine · 2026-08-09 · 赛后自动复盘</div>

</div>
</div>
</body>
</html>'''

with open('predictions_20260809.html', 'w', encoding='utf-8') as f:
    f.write(html)

# ── 控制台 ────────────────────────────────────────
print(f'✅ 多维报告: predictions_20260809.html ({len(html):,} bytes)')
print()
print(f'📋 模拟下注 ({bet_matches}场/{total_lines}注, ¥{total_stakes})')
print(f'{"─" * 80}')
for b in bets:
    if b['lines']:
        print(f'  {b["match_num"]} {b["match"]} [{b["league"]}]')
        for line in b['lines']:
            odds_str = f'@{line["odds"]:.2f}' if line['odds'] else ''
            print(f'    {line["dim"]} → {line["direction"]} {odds_str} 凯利{line["kelly"]:.1%} ¥{line["stake"]}')
print(f'{"─" * 80}')
print(f'待补充: 半场让球/半场大小球/角球 (需新数据)')
