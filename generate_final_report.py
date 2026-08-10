"""生成终盘A完整HTML报告 — 三维预测 + 投注单"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-10'

# Load data
preds = json.loads(pathlib.Path('data/output/predictions_2026-08-10.json').read_text('utf-8'))
kambi = json.loads(pathlib.Path('data/kambi_odds_2026-08-10.json').read_text('utf-8'))
bets = json.loads(pathlib.Path('data/output/pinnacle_bets_2026-08-10.json').read_text('utf-8'))

TEAM_CN = {
    'IK Sirius': '天狼星', 'IF Brommapojkarna': '布鲁马波卡纳',
    'Västerås SK': '韦斯特罗斯', 'Djurgårdens IF': '佐加顿斯',
    'Santa Clara': '圣克拉拉', 'Nacional': '葡萄牙国民',
}
LEAGUE_CN = {'SWE': '瑞典超', 'PPL': '葡超'}

def cn(h): return TEAM_CN.get(h, h)

# Build match data
matches = []
for p in preds:
    h = p['home_team']; a = p['away_team']
    m = p['model']; v = p.get('value', {}); b = p.get('bayesian', {})
    odds = p.get('odds', {})

    # Find Kambi data for this match
    k_entry = None
    for ke in kambi:
        if ke['home_team'] == h and ke['away_team'] == a:
            k_entry = ke; break

    k_h2h = k_spread = k_total = None
    if k_entry:
        for mkt in k_entry['bookmakers'][0]['markets']:
            if mkt['key'] == 'h2h' and mkt['outcomes']:
                o = mkt['outcomes']
                k_h2h = {'home': o[0]['price'], 'draw': o[1]['price'], 'away': o[2]['price']}
            elif mkt['key'] == 'spreads' and mkt['outcomes']:
                o = mkt['outcomes']
                k_spread = {'hdp': o[0]['point'], 'home_odds': o[0]['price'], 'away_odds': o[1]['price']}
            elif mkt['key'] == 'totals' and mkt['outcomes']:
                o = mkt['outcomes']
                k_total = {'line': o[0]['point'], 'over': o[0]['price'], 'under': o[1]['price']}

    matches.append({
        'home': cn(h), 'away': cn(a), 'league': LEAGUE_CN.get(p['league_code'], p['league_code']),
        'elo_diff': p['elo_diff'], 'cold': p['cold_start'],
        # Model probs
        'm_home': m['home_win'], 'm_draw': m['draw'], 'm_away': m['away_win'],
        'over25': m['over_25'], 'over35': m['over_35'],
        'exp_goals': m['lambda_home'] + m['lambda_away'],
        # Value
        'edge_home': v.get('home_edge', 0), 'edge_draw': v.get('draw_edge', 0), 'edge_away': v.get('away_edge', 0),
        'best': v.get('best_direction', '?'),
        # Kambi
        'k_h2h': k_h2h, 'k_spread': k_spread, 'k_total': k_total,
    })

# Bet slip
bet_slip = bets.get('bets', [])
total_stake = bets.get('total', 0)

DIR_CN = {'home': '主胜', 'draw': '平局', 'away': '客胜'}

def pct(v): return f'{v*100:.1f}%'
def odds_str(o): return f'{o:.2f}' if o else '-'
def edge_cls(v, threshold=0.05):
    if v > threshold: return 'edge-up'
    if v < -threshold: return 'edge-down'
    return ''

# ===== Build HTML =====
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘A 三维预测 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#14161d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;
  --home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;
  --cyan:#00d4ff;--purple:#a78bfa;--pink:#ff6b9d;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:960px;margin:0 auto}}
.header{{text-align:center;padding:28px 0 20px;border-bottom:1px solid var(--border);margin-bottom:20px}}
.header h1{{font-size:1.3em}}
.header .sub{{color:var(--dim);font-size:0.8em;margin-top:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7em;margin-left:6px;vertical-align:middle}}
.badge-v3{{background:#1a3a5c;color:var(--cyan)}}
.badge-kambi{{background:#2a1a0a;color:var(--away)}}
.badge-live{{background:#1a2a1a;color:var(--green)}}

/* Match card */
.match{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:14px}}
.match-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}
.teams{{font-size:1.1em;font-weight:700}}
.vs{{color:var(--dim);margin:0 8px}}
.league-tag{{font-size:0.65em;background:var(--border);padding:3px 8px;border-radius:4px;color:var(--dim)}}

/* 3D grid */
.dim-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:8px}}
@media(max-width:700px){{.dim-grid{{grid-template-columns:1fr}}}}
.dim{{background:rgba(255,255,255,0.015);border:1px solid var(--border);border-radius:8px;padding:12px}}
.dim-title{{font-size:0.7em;color:var(--dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:1px}}
.prob-row{{display:flex;align-items:center;margin-bottom:4px;font-size:0.8em}}
.prob-label{{width:36px;text-align:right;margin-right:8px;flex-shrink:0;font-size:0.85em}}
.prob-bar-wrap{{flex:1;height:14px;background:var(--bg);border-radius:3px;overflow:hidden}}
.prob-bar{{height:100%;border-radius:3px}}
.prob-bar.h{{background:var(--home)}}.prob-bar.d{{background:var(--draw)}}.prob-bar.a{{background:var(--away)}}
.prob-pct{{width:48px;margin-left:8px;text-align:right;font-weight:600;font-size:0.8em}}

.detail-row{{display:flex;justify-content:space-between;font-size:0.75em;margin-top:4px;color:var(--dim)}}
.detail-row span{{color:var(--text)}}

/* Edge indicators */
.edge-up{{color:var(--green);font-weight:600}}
.edge-down{{color:var(--red)}}
.edge-neutral{{color:var(--dim)}}

/* Bet slip */
.bet-section{{background:var(--card);border:2px solid var(--green);border-radius:10px;padding:20px;margin-top:24px}}
.bet-section h2{{font-size:1em;margin-bottom:12px;color:var(--green)}}
.bet-table{{width:100%;border-collapse:collapse;font-size:0.85em}}
.bet-table th{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--border);color:var(--dim);font-size:0.75em}}
.bet-table td{{padding:10px 6px;border-bottom:1px solid rgba(255,255,255,0.03)}}
.bet-stake{{font-weight:700;color:var(--green)}}
.bet-summary{{display:flex;gap:16px;margin-top:14px;font-size:0.85em}}
.bet-summary .stat{{color:var(--dim)}}
.bet-summary .stat b{{color:var(--text)}}
.bet-dim-tag{{display:inline-block;padding:2px 6px;border-radius:4px;font-size:0.7em;font-weight:600}}
.dim-1x2{{background:rgba(77,166,255,0.15);color:var(--home)}}
.dim-ah{{background:rgba(167,139,250,0.15);color:var(--purple)}}
.dim-ou{{background:rgba(255,107,157,0.15);color:var(--pink)}}

.cold-tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:0.65em;background:rgba(192,38,211,0.15);color:#e879f9}}

.footer{{text-align:center;padding:28px;color:var(--dim);font-size:0.7em;border-top:1px solid var(--border);margin-top:28px}}
.footer a{{color:var(--cyan)}}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🔴 终盘A 三维预测<span class="badge badge-v3">v3.0</span><span class="badge badge-kambi">Kambi</span></h1>
  <div class="sub">{date_str} · Dixon-Coles + Kambi三线(1X2+亚盘+大小球) · Shin去水 · 1/4 Kelly</div>
</div>
'''

# Match cards
for i, m in enumerate(matches):
    # Determine best edge direction for each dim

    # 1X2
    best_1x2 = max([(m['edge_home'], '主胜', m['m_home']), (m['edge_draw'], '平局', m['m_draw']), (m['edge_away'], '客胜', m['m_away'])], key=lambda x: x[0])

    html += f'''
<div class="match">
  <div class="match-header">
    <div class="teams">{m['home']} <span class="vs">vs</span> {m['away']}</div>
    <div class="league-tag">{m['league']}{' · ELO差'+str(int(m['elo_diff']))}</div>
  </div>
  <div class="dim-grid">
    <!-- DIM 1: 1X2 -->
    <div class="dim">
      <div class="dim-title">📊 胜平负</div>
      <div class="prob-row"><span class="prob-label">主</span><div class="prob-bar-wrap"><div class="prob-bar h" style="width:{m['m_home']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['m_home'])}</span></div>
      <div class="prob-row"><span class="prob-label">平</span><div class="prob-bar-wrap"><div class="prob-bar d" style="width:{m['m_draw']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['m_draw'])}</span></div>
      <div class="prob-row"><span class="prob-label">客</span><div class="prob-bar-wrap"><div class="prob-bar a" style="width:{m['m_away']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['m_away'])}</span></div>
      <div class="detail-row" style="margin-top:10px">
        <span>Kambi: </span>
        <span>主{odds_str(m['k_h2h']['home'] if m['k_h2h'] else None)} / 平{odds_str(m['k_h2h']['draw'] if m['k_h2h'] else None)} / 客{odds_str(m['k_h2h']['away'] if m['k_h2h'] else None)}</span>
      </div>
      <div class="detail-row">
        <span>Edge: 主<span class="{edge_cls(m['edge_home'])}">{pct(m['edge_home'])}</span> 平<span class="{edge_cls(m['edge_draw'])}">{pct(m['edge_draw'])}</span> 客<span class="{edge_cls(m['edge_away'])}">{pct(m['edge_away'])}</span></span>
      </div>
    </div>
    <!-- DIM 2: 亚洲盘 -->
    <div class="dim">
      <div class="dim-title">🏹 亚洲盘</div>
'''

    if m['k_spread']:
        hdp = m['k_spread']['hdp']
        if hdp > 0.01:
            desc = f"主队受+{hdp:.2f}"
        elif hdp < -0.01:
            desc = f"主队让{abs(hdp):.2f}"
        else:
            desc = "平手盘"
        html += f'''
      <div class="detail-row"><span>Kambi公平盘口: {desc}</span></div>
      <div class="detail-row"><span>主赔: {odds_str(m['k_spread']['home_odds'])} / 客赔: {odds_str(m['k_spread']['away_odds'])}</span></div>
'''
    else:
        html += '<div class="detail-row"><span>无亚洲盘数据</span></div>'

    html += '''
    </div>
    <!-- DIM 3: 大小球 -->
    <div class="dim">
      <div class="dim-title">⚽ 大小球</div>
'''
    html += f'''
      <div class="detail-row"><span>大2.5球: {pct(m['over25'])}</span><span>大3.5球: {pct(m['over35'])}</span></div>
      <div class="detail-row"><span>预期总进球: {m['exp_goals']:.2f}</span></div>
'''
    if m['k_total']:
        html += f'''      <div class="detail-row"><span>Kambi 盘口{odds_str(m['k_total']['line'])}: 大@{odds_str(m['k_total']['over'])} / 小@{odds_str(m['k_total']['under'])}</span></div>
'''
    html += '    </div>\n  </div>\n</div>\n'

# ===== BET SLIP =====
html += '''
<div class="bet-section">
  <h2>💰 投注单</h2>
'''

if bet_slip:
    html += '''
  <table class="bet-table">
    <tr><th>#</th><th>比赛</th><th>维度</th><th>方向</th><th>赔率</th><th>Kelly</th><th>金额</th></tr>
'''
    for i, b in enumerate(bet_slip):
        dim_cls = 'dim-ah' if '亚洲' in b['dim'] else ('dim-ou' if '大小' in b['dim'] else 'dim-1x2')
        cold = '<span class="cold-tag">冷启动</span>' if b.get('cold') else ''
        html += f'''    <tr>
      <td>{i+1}</td><td>{b['home']} vs {b['away']} {cold}</td>
      <td><span class="bet-dim-tag {dim_cls}">{b['dim']}</span></td>
      <td>{b['direction']}</td>
      <td>{b['odds']:.2f}</td>
      <td class="edge-up">{b['kelly']:.0%}</td>
      <td class="bet-stake">¥{b['stake']}</td>
    </tr>\n'''
    html += '  </table>\n'

    dims = {}
    for b in bet_slip: dims[b['dim']] = dims.get(b['dim'], 0) + 1

    source = bets.get('source', '?')
    html += f'''
  <div class="bet-summary">
    <div class="stat">注数: <b>{len(bet_slip)}</b></div>
    <div class="stat">总金额: <b>¥{total_stake}</b></div>
    <div class="stat">仓位: <b>{total_stake/100:.1f}%</b></div>
    <div class="stat">分布: <b>{dims}</b></div>
    <div class="stat">数据源: <b>{source}</b></div>
  </div>
'''
else:
    html += '<p style="color:var(--dim)">0注通过筛选 · edge>5% + Kelly>1% + 非冷启动 + 方向≥35% 全部未满足</p>'

html += f'''
</div>

<div class="footer">
  足球预测模型 v3.0 &middot; Dixon-Coles + Kambi三线 &middot; Shin去水 &middot; 1/4 Kelly<br>
  生成时间: {date_str} &middot; 仅供参考 · 历史表现不代表未来结果<br>
  <a href="../archive.html" style="color:var(--dim)">← 返回档案</a>
</div>
</div>
</body>
</html>'''

out_path = pathlib.Path(f'data/output/final_bets_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'HTML report saved to {out_path}')
