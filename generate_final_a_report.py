"""终盘A投注报告 HTML · v3.1 · 体彩数据 · 市场驱动冷启动"""
import json, sys, io, pathlib
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')

preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
bets_data = json.loads(pathlib.Path(f'data/output/pinnacle_bets_{date_str}.json').read_text('utf-8'))
bets = bets_data.get('bets', []) if isinstance(bets_data, dict) else bets_data
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))

match_map = {}
for m in today:
    match_map[f"{m['home_team']}|{m['away_team']}"] = m

def pct(v): return f'{v*100:.1f}%'

total = len(preds)
cold = sum(1 for p in preds if p.get('cold_start') or p.get('model',{}).get('cold_start'))
bet_count = len(bets)
total_stake = sum(b.get('stake', 0) for b in bets)

rows = ''
for p in preds:
    m = p.get('model', p)
    h, a = p['home_team'], p['away_team']
    key = f'{h}|{a}'
    info = match_map.get(key, {})
    cs = p.get('cold_start') or m.get('cold_start', False)
    cs_detail = m.get('cold_start_detail', {})
    mi = cs_detail.get('market_informed', False)
    mlam = cs_detail.get('market_lam')

    odds = info.get('odds', {})
    handicap = info.get('handicap')
    ah_odds = info.get('ah_odds', {})
    elo_diff = p.get('elo_diff', 0)

    hp, dp, ap = m['home_win'], m['draw'], m['away_win']
    best = max([('H', hp), ('D', dp), ('A', ap)], key=lambda x: x[1])
    best_cn = {'H': '主胜', 'D': '平局', 'A': '客胜'}[best[0]]

    # Market-implied probs from odds via Shin devig
    if odds:
        from models.odds import implied_probability
        imp = implied_probability(odds['home'], odds['draw'], odds['away'])
        mkt_h, mkt_d, mkt_a = imp['home'], imp['draw'], imp['away']
        mkt_dir = ['H', 'D', 'A'][max(range(3), key=lambda i: [mkt_h, mkt_d, mkt_a][i])]
        mkt_dir_cn = {'H': '主胜', 'D': '平局', 'A': '客胜'}[mkt_dir]
        agree = '一致' if best[0] == mkt_dir else '冲突'
    else:
        mkt_h = mkt_d = mkt_a = 0
        mkt_dir_cn = '—'
        agree = ''

    # Handicap
    if handicap is not None:
        gl = int(handicap)
        hcap_str = f'主让{abs(gl)}' if gl < 0 else (f'主受{gl}' if gl > 0 else '平手')
        ah_str = f'{hcap_str} 主{ah_odds.get("home","-")}/{ah_odds.get("draw","-")}/{ah_odds.get("away","-")}'
    else:
        ah_str = '—'

    # O/U
    ou_line = info.get('ou_line')
    over_odds = info.get('over_odds')
    under_odds = info.get('under_odds')
    if ou_line and over_odds:
        ou_str = f'O{ou_line} 大{over_odds}/小{under_odds}'
        ou_model = f'模型: 大{pct(m["over_25"])} / 小{pct(1-m["over_25"])}'
    else:
        ou_str = '—'
        ou_model = ''

    # Cold start badge
    cs_badge = ''
    if cs:
        if mi:
            cs_badge = ' 🧊→📊市场驱动'
        else:
            cs_badge = ' 🧊冷启动'

    # Agreement badge
    agree_badge = ''
    if agree == '冲突':
        agree_badge = ' ⚠️方向冲突'
    elif agree == '一致':
        agree_badge = ''

    # Match bets
    match_bets = []
    for b in bets:
        bh = b.get('home', '')
        if bh[:15].lower() in h.lower()[:20] or h.lower()[:15] in bh.lower()[:20]:
            match_bets.append(b)

    bet_html = ''
    for b in match_bets:
        bet_html += f'''<div class="bet-line">
  <span>{b['dim']}</span>
  <span class="bet-dir">{b['direction']}</span>
  <span>@{b['odds']}</span>
  <span>Kelly<b>{b['kelly']*100:.1f}%</b></span>
  <span class="stake">¥{b['stake']}</span>
</div>'''

    rows += f'''<div class="card">
<div class="teams">
  <span class="name">{h} <i>vs</i> {a}</span>
  <span class="info">{info.get('league_name','')} · ELO差{elo_diff:+.0f}{cs_badge}{agree_badge}</span>
</div>
<div class="grid">
  <div class="dim">
    <div class="dim-title">1X2 胜平负</div>
    <div class="bars">
      <div class="bar-row"><span class="lbl h">主</span><div class="bar"><div class="fill h" style="width:{hp*100}%"></div></div><span class="val">{pct(hp)}</span></div>
      <div class="bar-row"><span class="lbl d">平</span><div class="bar"><div class="fill d" style="width:{dp*100}%"></div></div><span class="val">{pct(dp)}</span></div>
      <div class="bar-row"><span class="lbl a">客</span><div class="bar"><div class="fill a" style="width:{ap*100}%"></div></div><span class="val">{pct(ap)}</span></div>
    </div>
    <div class="meta">模型{best_cn} · 市场{mkt_dir_cn} · 体彩{odds.get('home','-')}/{odds.get('draw','-')}/{odds.get('away','-')}</div>
  </div>
  <div class="dim">
    <div class="dim-title">让球盘 HHAD</div>
    <div class="ah">{ah_str}</div>
    {f'<div class="meta">O2.5 {ou_model}</div>' if ou_model else ''}
  </div>
  <div class="dim">
    <div class="dim-title">大小球 O/U 2.5</div>
    <div class="ou">{ou_str}</div>
    {bet_html}
  </div>
</div>
</div>'''

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘A投注 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#13151d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:850px;margin:0 auto}}
.hdr{{text-align:center;padding:24px 0 16px;border-bottom:2px solid var(--border);margin-bottom:20px}}
.hdr h1{{font-size:1.2em}}.hdr .sub{{color:var(--dim);font-size:0.72em;margin-top:4px}}
.tag{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.65em;font-weight:700;margin:0 4px}}
.tag-a{{background:#3a1a0a;color:var(--red)}}.tag-v{{background:#1a3a5c;color:var(--cyan)}}

.kpi{{display:flex;gap:8px;margin-bottom:20px}}
.k{{flex:1;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center}}
.k .n{{font-size:1.4em;font-weight:800}}.k .lb{{font-size:0.6em;color:var(--dim);margin-top:3px}}
.k.g .n{{color:var(--green)}}.k.r .n{{color:var(--red)}}.k.c .n{{color:var(--cyan)}}

.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:10px}}
.teams{{display:flex;justify-content:space-between;margin-bottom:12px}}
.teams .name{{font-weight:700;font-size:0.95em}}.teams i{{color:var(--dim);margin:0 8px;font-weight:400;font-style:normal}}
.teams .info{{font-size:0.65em;color:var(--dim)}}
.grid{{display:flex;gap:14px}}
.dim{{flex:1;background:var(--bg);border-radius:8px;padding:12px}}
.dim-title{{font-size:0.65em;color:var(--dim);font-weight:700;margin-bottom:8px;letter-spacing:1px}}

.bar-row{{display:flex;align-items:center;margin-bottom:3px;font-size:0.72em}}
.lbl{{width:14px;text-align:center;font-weight:700;font-size:0.75em}}
.lbl.h{{color:var(--home)}}.lbl.d{{color:var(--draw)}}.lbl.a{{color:var(--away)}}
.bar{{flex:1;height:7px;background:rgba(255,255,255,0.03);border-radius:4px;overflow:hidden;margin:0 6px}}
.fill{{height:100%;border-radius:4px}}.fill.h{{background:var(--home)}}.fill.d{{background:var(--draw)}}.fill.a{{background:var(--away)}}
.val{{width:40px;text-align:right;font-weight:600;font-size:0.72em}}

.meta{{font-size:0.62em;color:var(--dim);margin-top:6px}}
.ah,.ou{{font-size:0.8em;font-weight:600;padding:4px 0}}

.bet-line{{display:flex;gap:6px;align-items:center;margin-top:8px;padding:6px 8px;background:rgba(63,185,80,0.06);border-radius:6px;font-size:0.7em}}
.bet-dir{{color:var(--green);font-weight:700}}.stake{{margin-left:auto;color:var(--green);font-weight:800}}

.rule-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:16px}}
.rule-box h3{{font-size:0.82em;color:var(--cyan);margin-bottom:6px}}
.rule-box p{{font-size:0.68em;color:var(--dim);line-height:1.7}}

.ftr{{text-align:center;padding:20px;color:var(--dim);font-size:0.62em;border-top:1px solid var(--border);margin-top:20px}}
</style>
</head>
<body>
<div class="container">
<div class="hdr">
  <h1>🔴 终盘A 投注单<span class="tag tag-a">终盘A</span><span class="tag tag-v">v3.1</span></h1>
  <div class="sub">{date_str} · 体彩三盘(SPF+HHAD+TTG) · ≤21:00开踢 · 市场驱动冷启动 · Dixon-Coles + Shin去水 + 1/4 Kelly</div>
</div>

<div class="kpi">
  <div class="k c"><div class="n">{total}</div><div class="lb">竞彩场次</div></div>
  <div class="k"><div class="n">{cold}</div><div class="lb">冷启动</div></div>
  <div class="k"><div class="n">{total-cold}</div><div class="lb">已知ELO</div></div>
  <div class="k g"><div class="n">{bet_count}</div><div class="lb">投注信号</div></div>
  <div class="k"><div class="n">¥{total_stake}</div><div class="lb">建议仓位</div></div>
</div>

<div class="rule-box">
  <h3>📋 筛选规则</h3>
  <p>
    <b>通过条件:</b> edge &gt; 5% + Kelly &gt; 1% + 非冷启动 + 方向概率 &ge; 35%<br>
    <b>三维覆盖:</b> 1X2 (胜平负) + 让球盘 (HHAD) + 大小球 (O/U 2.5 从TTG总进球反推)<br>
    <b>v3.1 冷启动修复:</b> 未知球队用体彩市场赔率反推λ参数(KL最小化)，不再盲猜45.5%<br>
    <b>数据源降级链:</b> odds-api.io → the-odds-api → 体彩(当前)
  </p>
</div>

{rows}

<div class="rule-box">
  <h3>💰 投注单 ({bet_count}注 · ¥{total_stake} · {total_stake/10000*100:.1f}%仓位)</h3>
'''

if bets:
    for b in bets:
        html += f'''<div style="display:flex;gap:12px;align-items:center;padding:10px 14px;background:var(--bg);border-radius:8px;margin-bottom:4px;font-size:0.82em">
  <span style="font-weight:700;flex:2">{b['home']} vs {b['away']}</span>
  <span style="color:var(--dim);font-size:0.7em;flex:1">{b['league']}</span>
  <span style="background:var(--border);padding:2px 8px;border-radius:4px;font-size:0.7em">{b['dim']}</span>
  <span style="color:var(--green);font-weight:700;flex:1">{b['direction']} @{b['odds']}</span>
  <span style="color:var(--cyan);flex:0 0 100px">Kelly {b['kelly']*100:.1f}%</span>
  <span style="color:var(--green);font-weight:800;font-size:1.1em">¥{b['stake']}</span>
</div>'''
else:
    html += '<p style="color:var(--dim);font-size:0.72em">0注通过筛选 · 冷启动或edge不足 · 今日休盘</p>'

html += f'''
</div>

<div class="ftr">
  足球预测模型 v3.1 · 终盘A {date_str} · 体彩独家数据<br>
  ⚠ 仅供研究参考 · 理性购彩 · 不构成投注建议
</div>
</div></body></html>'''

out_path = pathlib.Path(f'data/output/final_bets_a_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'终盘A报告: {out_path}')
print(f'{total}场 · {cold}冷启动 · {bet_count}注 ¥{total_stake}')
