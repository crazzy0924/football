"""生成早盘预测HTML报告 · 2026-08-11"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-11'

preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
pinnacle_odds = pathlib.Path(f'data/pinnacle_odds_{date_str}.json')
odds_data = json.loads(pinnacle_odds.read_text('utf-8')) if pinnacle_odds.exists() else []
bets_file = pathlib.Path(f'data/output/pinnacle_bets_{date_str}.json')
bets = json.loads(bets_file.read_text('utf-8')) if bets_file.exists() else {'bets': [], 'total': 0}

TEAM_CN = {
    'IK Sirius': '天狼星', 'IF Brommapojkarna': '布鲁马波卡纳',
    'Västerås SK': '韦斯特罗斯', 'Djurgårdens IF': '佐加顿斯',
    'Santa Clara': '圣克拉拉', 'Nacional': '葡萄牙国民',
    'Audax Italiano': '奥达克斯意大利人', 'Nublense': '努布伦斯',
    'FC CFR 1907 Cluj': '克卢日', 'FC Universitatea Cluj': '克卢日大学',
    'Plymouth Argyle': '普利茅斯', 'Exeter City': '埃克塞特城',
    'Silkeborg IF': '锡尔克堡', 'Odense Boldklub': '欧登塞',
    'Mura Murska Sobota': '穆拉', 'NK Radomlje': '拉多姆利',
    'POFC Botev Vratsa': '博特夫弗拉察', 'PFC Slavia Sofia': '索菲亚斯拉维亚',
    'FC Fakel Voronezh': '沃罗涅日火炬', 'RFK Akhmat Grozny': '格罗兹尼艾哈迈德',
    'Botev Plovdiv': '普罗夫迪夫博特夫', 'FK Spartak 1918 Varna': '瓦尔纳斯巴达',
    'ACS Sepsi OSK Sfantu Gheorghe': '圣格奥尔基塞普西', 'Fotbal Club FCSB': '布加勒斯特星',
}
LEAGUE_CN = {
    'SWE': '瑞典超', 'PPL': '葡超', 'CHI': '智利甲', 'ROM': '罗甲',
    'EFL': '英联杯', 'DEN': '丹超', 'SVN': '斯洛文尼亚甲', 'BUL': '保加利亚甲',
    'RPL': '俄超',
}

def cn(h): return TEAM_CN.get(h, h)

# Build odds lookup
odds_map = {}
for e in odds_data:
    h = e['home_team']; a = e['away_team']
    for bm in e.get('bookmakers', []):
        for mkt in bm['markets']:
            if mkt['key'] == 'h2h':
                o = mkt['outcomes']
                odds_map[(h,a)] = {'h2h': {'home': o[0]['price'], 'draw': o[1]['price'], 'away': o[2]['price']}}
            elif mkt['key'] == 'spreads':
                o = mkt['outcomes']
                if (h,a) not in odds_map: odds_map[(h,a)] = {}
                odds_map[(h,a)]['ah'] = {'hdp': o[0]['point'], 'home': o[0]['price'], 'away': o[1]['price']}
            elif mkt['key'] == 'totals':
                o = mkt['outcomes']
                if (h,a) not in odds_map: odds_map[(h,a)] = {}
                odds_map[(h,a)]['ou'] = {'line': o[0]['point'], 'over': o[0]['price'], 'under': o[1]['price']}

# Stats
total = len(preds)
cold_count = sum(1 for p in preds if p['cold_start'])
has_odds = sum(1 for p in preds if (p['home_team'], p['away_team']) in odds_map)
finished = sum(1 for p in preds if p.get('status') == 'settled')
bet_count = len(bets.get('bets', []))

def pct(v): return f'{v*100:.1f}%'
def odds_str(o): return f'{o:.2f}' if o else '-'

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>早盘预测 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#14161d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;
  --home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;
  --cyan:#00d4ff;--purple:#a78bfa;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:1000px;margin:0 auto}}
.header{{text-align:center;padding:28px 0 20px;border-bottom:1px solid var(--border);margin-bottom:20px}}
.header h1{{font-size:1.3em}}.header .sub{{color:var(--dim);font-size:0.8em;margin-top:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7em;margin-left:6px}}
.badge-v3{{background:#1a3a5c;color:var(--cyan)}}.badge-cold{{background:rgba(192,38,211,0.2);color:#e879f9}}

.summary{{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}}
.stat-card{{flex:1;min-width:110px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;text-align:center}}
.stat-card .n{{font-size:1.5em;font-weight:800}}
.stat-card .l{{font-size:0.65em;color:var(--dim);margin-top:2px}}
.stat-card.warn{{border-color:rgba(248,81,73,0.3)}}.stat-card.warn .n{{color:var(--red)}}
.stat-card.ok{{border-color:rgba(63,185,80,0.3)}}.stat-card.ok .n{{color:var(--green)}}

.match{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:10px}}
.match-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.teams{{font-size:1em;font-weight:700}}.vs{{color:var(--dim);margin:0 6px}}
.meta{{display:flex;gap:8px;align-items:center}}
.league-tag{{font-size:0.6em;background:var(--border);padding:2px 7px;border-radius:4px;color:var(--dim)}}
.status-tag{{font-size:0.6em;padding:2px 7px;border-radius:4px;font-weight:600}}
.st-live{{background:rgba(248,81,73,0.15);color:var(--red)}}
.st-done{{background:rgba(101,103,120,0.15);color:var(--dim)}}
.st-upcoming{{background:rgba(63,185,80,0.1);color:var(--green)}}

.prob-row{{display:flex;align-items:center;margin-bottom:3px;font-size:0.78em}}
.prob-label{{width:28px;text-align:right;margin-right:6px;font-size:0.85em}}
.prob-bar-wrap{{flex:1;height:12px;background:var(--bg);border-radius:3px;overflow:hidden}}
.prob-bar{{height:100%;border-radius:3px}}
.prob-bar.h{{background:var(--home)}}.prob-bar.d{{background:var(--draw)}}.prob-bar.a{{background:var(--away)}}
.prob-pct{{width:44px;margin-left:6px;text-align:right;font-weight:600;font-size:0.78em}}

.detail-row{{display:flex;justify-content:space-between;font-size:0.72em;margin-top:3px;color:var(--dim)}}
.detail-row span{{color:var(--text)}}

.odds-section{{margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.03);font-size:0.73em}}
.odds-section .label{{color:var(--dim);margin-right:8px}}

.cold-banner{{background:rgba(192,38,211,0.08);border:1px solid rgba(192,38,211,0.2);border-radius:6px;padding:8px 12px;font-size:0.73em;color:#e879f9;margin-top:8px}}
.warning-box{{background:rgba(248,81,73,0.05);border:1px solid rgba(248,81,73,0.2);border-radius:6px;padding:12px 16px;margin-top:14px;font-size:0.78em}}
.warning-box b{{color:var(--red)}}

.footer{{text-align:center;padding:28px;color:var(--dim);font-size:0.7em;border-top:1px solid var(--border);margin-top:28px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🌅 早盘预测<span class="badge badge-v3">v3.0</span></h1>
  <div class="sub">{date_str} · Dixon-Coles + 联赛画像 + 12场覆盖 · the-odds-api.com配额耗尽(回退odds-api.io)</div>
</div>

<div class="summary">
  <div class="stat-card"><div class="n">{total}</div><div class="l">总场次</div></div>
  <div class="stat-card warn"><div class="n">{cold_count}</div><div class="l">冷启动 ⚠️</div></div>
  <div class="stat-card"><div class="n">{has_odds}</div><div class="l">有赔率</div></div>
  <div class="stat-card"><div class="n">{bet_count}</div><div class="l">投注信号</div></div>
  <div class="stat-card ok"><div class="n">{total - cold_count}</div><div class="l">ELO就绪</div></div>
</div>
'''

# Warning box for overall situation
html += f'''
<div class="warning-box">
  <b>⚠ API配额告急</b> · the-odds-api.com v4 500/500耗尽 · odds-api.io v3仅Kambi+Unibet · 11/12场赔率缺失 · {cold_count}/12场冷启动(默认联赛均值)
</div>
'''

# Match cards
for p in preds:
    h = p['home_team']; a = p['away_team']
    m = p['model']; cs = p['cold_start']
    h_cn = cn(h); a_cn = cn(a)
    lc = p['league_code']; league_cn = LEAGUE_CN.get(lc, lc)

    odds = odds_map.get((h, a), {})
    o_h2h = odds.get('h2h')

    # Status determination
    # For now, mark live match, finished ones based on kickoff time
    status = 'upcoming'
    if (h, a) == ('Audax Italiano', 'Nublense'):
        status = 'live'
    # Swedish/Portuguese matches already finished (kicked off 01:00-03:15 BJT)
    if lc in ('SWE', 'PPL', 'DEN', 'SVN', 'BUL', 'RPL', 'ROM', 'EFL'):
        status = 'done'  # morning matches already finished

    st_cls = {'live': 'st-live', 'done': 'st-done', 'upcoming': 'st-upcoming'}.get(status, '')
    st_text = {'live': '进行中', 'done': '已完赛', 'upcoming': '未开赛'}.get(status, '')

    html += f'''
<div class="match">
  <div class="match-header">
    <div class="teams">{h_cn} <span class="vs">vs</span> {a_cn}</div>
    <div class="meta">
      <span class="league-tag">{league_cn} · 差{int(p['elo_diff'])}</span>
      <span class="status-tag {st_cls}">{st_text}</span>
    </div>
  </div>
  <div class="prob-row"><span class="prob-label">主</span><div class="prob-bar-wrap"><div class="prob-bar h" style="width:{m['home_win']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['home_win'])}</span></div>
  <div class="prob-row"><span class="prob-label">平</span><div class="prob-bar-wrap"><div class="prob-bar d" style="width:{m['draw']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['draw'])}</span></div>
  <div class="prob-row"><span class="prob-label">客</span><div class="prob-bar-wrap"><div class="prob-bar a" style="width:{m['away_win']*100:.0f}%"></div></div><span class="prob-pct">{pct(m['away_win'])}</span></div>
  <div class="detail-row"><span>预期进球: {m['lambda_home']+m['lambda_away']:.2f}</span><span>大2.5: {pct(m['over_25'])}</span></div>
'''

    if o_h2h:
        html += f'''
  <div class="odds-section">
    <span class="label">Kambi赔率:</span>
    <span>主{odds_str(o_h2h['home'])} / 平{odds_str(o_h2h['draw'])} / 客{odds_str(o_h2h['away'])}</span>
  </div>'''

    if cs:
        html += f'<div class="cold-banner">🧊 冷启动 — 球队ELO未收敛，使用{league_cn}联赛均值攻防参数</div>'

    if odds.get('ah'):
        ah = odds['ah']
        hdp = ah['hdp']
        if hdp > 0.01: desc = f'主受+{hdp:.2f}'
        elif hdp < -0.01: desc = f'主让{abs(hdp):.2f}'
        else: desc = '平手'
        html += f'<div class="odds-section"><span class="label">亚洲盘(Kambi):</span> {desc} · 主{odds_str(ah["home"])} 客{odds_str(ah["away"])}</div>'
    if odds.get('ou'):
        ou = odds['ou']
        html += f'<div class="odds-section"><span class="label">大小球(Kambi):</span> 盘口{ou["line"]} · 大{odds_str(ou["over"])} 小{odds_str(ou["under"])}</div>'

    html += '</div>\n'

# Bet section
html += '''
<div style="margin-top:20px;background:var(--card);border:2px solid var(--green);border-radius:8px;padding:16px;">
  <h2 style="font-size:0.9em;color:var(--green);margin-bottom:8px;">💰 投注信号</h2>
'''
bet_slip = bets.get('bets', [])
if bet_slip:
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.8em">'
    html += '<tr><th style="text-align:left;padding:6px;border-bottom:1px solid var(--border)">#</th><th style="text-align:left">比赛</th><th>维度</th><th>方向</th><th>赔率</th><th>金额</th></tr>'
    for i, b in enumerate(bet_slip):
        html += f'<tr><td style="padding:6px">{i+1}</td><td>{b["home"]} vs {b["away"]}</td><td>{b["dim"]}</td><td>{b["direction"]}</td><td>{b["odds"]:.2f}</td><td style="color:var(--green);font-weight:700">¥{b["stake"]}</td></tr>'
    html += '</table>'
else:
    html += '<p style="color:var(--dim);font-size:0.8em;">⚠ 0注通过筛选 · 唯一有赔率的场次(Audax Italiano vs Nublense)为冷启动+进行中 · edge>5%+Kelly>1%+非冷启动+方向≥35%均未满足</p>'

html += f'''
</div>
<div class="footer">
  足球预测模型 v3.0 · Dixon-Coles · {date_str} 早盘<br>
  配额耗尽预警: the-odds-api.com 500/500 · 回退odds-api.io Kambi/Unibet<br>
  数据源: odds-api.io v3 · 仅供参考
</div>
</div></body></html>'''

out_path = pathlib.Path(f'data/output/early_analysis_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'早盘报告: {out_path}')
