# -*- coding: utf-8 -*-
"""生成终盘A HTML · 2026-08-14 · ≤21:00开球仅1场(东京绿茵) · 翻市场拦截0注 · 埃尔夫斯堡注单待终盘B"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-14'
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))
morning = json.loads(pathlib.Path('data/pinnacle_morning_2026-08-14.json').read_text('utf-8'))

from pipeline.reporter import TEAM_CN

def cn(name):
    return TEAM_CN.get(name, name)

morning_spf = {}
for e in morning:
    for bm in e.get('bookmakers', []):
        for mkt in bm['markets']:
            if mkt['key'] == 'h2h':
                morning_spf[(e['home_team'], e['away_team'])] = {o['name']: o['price'] for o in mkt['outcomes']}

cards = []
for p, m in zip(preds, today):
    ko = m.get('kickoff_time', '')
    if not ko or ko > '21:00':
        continue  # 终盘A只覆盖 ≤21:00 开球
    model = p['model']
    bayes = p.get('bayesian') or {}
    post = bayes.get('posterior', {})
    value = p.get('value') or {}
    o = m.get('odds', {})
    ah = m.get('ah_odds', {})
    old = morning_spf.get((p['home_team'], p['away_team']), {})
    mv = []
    for name, price in o.items():
        if name in old and old[name] > 0:
            chg = (price - old[name]) / old[name] * 100
            if abs(chg) >= 1:
                arrow = '↑' if chg > 0 else '↓'
                mv.append(f'{cn(name)}{old[name]}→{price}({arrow}{abs(chg):.0f}%)')
    mv_txt = ' · '.join(mv) if mv else '静止'
    m_dir = max(('home', model['home_win']), ('draw', model['draw']), ('away', model['away_win']), key=lambda x: x[1])[0]
    k_dir = min(o.items(), key=lambda kv: kv[1])[0] if o else None
    flip = bool(o) and m_dir != k_dir
    kelly = value.get('kelly', 0) or 0
    if p.get('cold_start'):
        verdict, vcls, why = '⛔ 拦截', 'no', '冷启动场次永不投注(市场即模型)'
    elif flip:
        verdict, vcls, why = '⛔ 拦截', 'no', f'翻市场纪律: 模型{ {"home":"主胜","draw":"平局","away":"客胜"}[m_dir] }42.7%≠市场({o[k_dir]:.2f}最低) · Kelly本可过线({kelly:.1%})但无翻市场资格(分歧2-2)'
    else:
        verdict, vcls, why = '✅ 信号', 'yes', f'Kelly={kelly:.1%}'
    cards.append({
        'home': cn(p['home_team']), 'away': cn(p['away_team']),
        'kickoff': ko, 'elo_h': p.get('elo_home', 0), 'elo_a': p.get('elo_away', 0),
        'odds_h': o.get('home') or '无', 'odds_d': o.get('draw') or '无', 'odds_a': o.get('away') or '无',
        'handicap': m.get('handicap'), 'ah': ah, 'ou': m.get('ou_line'),
        'over': m.get('over_odds'), 'under': m.get('under_odds'),
        'mh': model.get('home_win', 0), 'md': model.get('draw', 0), 'ma': model.get('away_win', 0),
        'ph': post.get('home', 0), 'pd': post.get('draw', 0), 'pa': post.get('away', 0),
        'verdict': verdict, 'vcls': vcls, 'why': why, 'mv': mv_txt,
    })

n_sig = sum(1 for c in cards if c['vcls'] == 'yes')
n_flip = sum(1 for c in cards if '翻市场' in c['why'])

rows = []
for c in cards:
    rows.append(f'''
  <div class="card">
    <h3>{c['home']} vs {c['away']}<span class="t"> 日职 · 北京 {c['kickoff']} 开踢</span></h3>
    <div class="meta-line">
      <span class="badge ok">非冷启动</span>
      <span>ELO {c['elo_h']:.0f} / {c['elo_a']:.0f}</span>
      <span>SPF {c['odds_h']} / {c['odds_d']} / {c['odds_a']}</span>
      <span>让球(主受1球) {c['ah'].get('home')}/{c['ah'].get('draw')}/{c['ah'].get('away')}</span>
      <span>大{c['over']}/小{c['under']} (线{c['ou']})</span>
      <span>移动: {c['mv']}</span>
    </div>
    <div class="prob-line">
      <span>模型 主{c['mh']:.1%} / 平{c['md']:.1%} / 客{c['ma']:.1%}</span>
      <span class="dim">→ 后验 主{c['ph']:.1%} / 平{c['pd']:.1%} / 客{c['pa']:.1%}</span>
    </div>
    <div class="signal {c['vcls']}">{c['verdict']} — {c['why']}</div>
  </div>''')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘A · 8月14日 · 早场(≤21:00)</title>
<style>
:root{{--bg:#0b0c10;--card:#13151d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;--purple:#a78bfa}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.6}}
.c{{max-width:820px;margin:0 auto}}
hdr{{display:block;text-align:center;padding:20px 0;border-bottom:2px solid var(--border);margin-bottom:18px}}
hdr h1{{font-size:1.12em}}hdr sub{{font-size:0.62em;color:var(--dim)}}
.kpi{{display:flex;gap:8px;margin-bottom:16px}}
.k{{flex:1;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center}}
.k .n{{font-size:1.35em;font-weight:800}}.k .lb{{font-size:0.56em;color:var(--dim);margin-top:3px}}
.k.g .n{{color:var(--green)}}.k.p .n{{color:var(--purple)}}.k.r .n{{color:var(--red)}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:10px}}
.card h3{{font-size:0.9em;margin-bottom:6px}}.card h3 .t{{font-size:0.62em;color:var(--dim);font-weight:400}}
.meta-line{{display:flex;flex-wrap:wrap;gap:8px;font-size:0.68em;color:var(--dim);margin-bottom:4px}}
.badge{{padding:1px 8px;border-radius:8px;font-size:0.62em;font-weight:700}}
.badge.ok{{background:rgba(63,185,80,0.1);color:var(--green)}}
.prob-line{{font-size:0.7em;margin-bottom:2px}}
.dim{{color:var(--dim)}}
.signal{{display:inline-block;margin-top:6px;padding:3px 10px;border-radius:6px;font-size:0.7em;font-weight:700}}
.signal.no{{background:rgba(248,81,73,0.08);color:var(--red)}}
.signal.yes{{background:rgba(63,185,80,0.1);color:var(--green)}}
.rule-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin:14px 0}}
.rule-box h3{{font-size:0.8em;color:var(--cyan);margin-bottom:6px}}
.rule-box p{{font-size:0.66em;color:var(--dim);line-height:1.7}}
.ftr{{text-align:center;padding:18px;color:var(--dim);font-size:0.55em;border-top:1px solid var(--border);margin-top:16px}}
</style>
</head>
<body><div class="c">

<hdr>
  <h1>🔴 终盘A · 早场(≤21:00开球)<span style="font-size:0.7em;color:var(--purple);margin-left:8px">v3.1</span></h1>
  <sub>2026年8月14日 · 临场赔率17:00后刷新 · 三线合并 · 今日仅1场≤21:00(东京绿茵18:00) · 其余16场23:00后开球归终盘B</sub>
</hdr>

<div class="kpi">
  <div class="k p"><div class="n">1</div><div class="lb">早场场次</div></div>
  <div class="k g"><div class="n">{n_sig}</div><div class="lb">投注信号</div></div>
  <div class="k r"><div class="n">{n_flip}</div><div class="lb">翻市场拦截</div></div>
  <div class="k"><div class="n">0</div><div class="lb">冷启动</div></div>
</div>
{''.join(rows)}

<div class="rule-box">
  <h3>📋 终盘A 结论 (0注)</h3>
  <p>
    <b>⛔ 东京绿茵 vs 柏太阳神:</b> 模型主胜42.7% (Kelly 5.96%本可过线) 但市场客胜1.79最低 → 翻市场纪律拦截。<br>
    且赔率移动 客胜1.84→1.79 — 资金持续流向客队, 模型方向既逆市场又逆移动, 双重反对。<br>
    <b>🧊 其余16场 (23:00-03:15开球) 全部归终盘B。</b><br>
    <b>🎫 埃尔夫斯堡主胜注单更新:</b> 赔率 1.65→1.62 (顺移), Kelly 17% ¥415 (4.2%仓位) — 01:00开球, 终盘B临场复核。<br>
    <b>📚 首轮回补说明:</b> ELO已重放(不伦瑞克+43.7/圣埃蒂安+34.0/波鸿-19.1), 但模型概率由DC参数驱动, ELO只影响展示/冷启动/复盘 — 故今晚德乙法乙概率未变(不伦瑞克客45.7%照旧拦截)。市场本身在动: 不伦瑞克主胜赔率2.38→2.18(-8.4%), 资金流向主队, 与模型方向背离。
  </p>
</div>

<div class="ftr">
  足球预测模型 v3.1 · 终盘A · 2026-08-14<br>
  ⚠ 仅供研究参考 · 理性购彩 · 不构成投注建议
</div>

</div></body></html>
'''

out = pathlib.Path(f'data/output/finalA_analysis_{date_str}.html')
out.write_text(html, encoding='utf-8')
print(f'✅ 终盘A报告已生成 → {out}')
