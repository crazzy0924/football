"""生成午盘更新HTML · 2026-08-14 · 早盘→午盘移动对比 · 1注维持(埃尔夫斯堡主胜) · 翻市场纪律4拦截"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-14'
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))
morning = json.loads(pathlib.Path('data/pinnacle_morning_2026-08-14.json').read_text('utf-8'))

from pipeline.reporter import TEAM_CN

LEAGUE_CN = {'J1': '日职', 'FIN': '芬超', 'BL2': '德乙', 'SWE': '瑞超', 'NOR': '挪超',
             'DED': '荷甲', 'DED2': '荷乙', 'FL2': '法乙', 'ELC': '英冠', 'PPL': '葡超', 'SPL': '沙特联'}

def cn(name):
    return TEAM_CN.get(name, name)

# 早盘价格映射 (用于移动对比)
morning_spf = {}
for e in morning:
    for bm in e.get('bookmakers', []):
        for mkt in bm['markets']:
            if mkt['key'] == 'h2h':
                morning_spf[(e['home_team'], e['away_team'])] = {o['name']: o['price'] for o in mkt['outcomes']}

cards = []
for p, m in zip(preds, today):
    model = p['model']
    bayes = p.get('bayesian') or {}
    post = bayes.get('posterior', {})
    value = p.get('value') or {}
    o = m.get('odds', {})
    ah = m.get('ah_odds', {})

    cold = p.get('cold_start', False)
    cold_tag = '双冷' if p.get('elo_home', 0) == 1500 and p.get('elo_away', 0) == 1500 else \
               '半冷' if cold else '非冷'
    cold_cls = 'cold' if cold else 'ok'

    # 移动对比
    mv_txt = ''
    old = morning_spf.get((p['home_team'], p['away_team']), {})
    if old and o:
        mv = []
        for name, price in o.items():
            if name in old and old[name] > 0:
                chg = (price - old[name]) / old[name] * 100
                if abs(chg) >= 1:
                    arrow = '↑' if chg > 0 else '↓'
                    mv.append(f'{cn(name)}{old[name]}→{price}({arrow}{abs(chg):.0f}%)')
        mv_txt = ' · '.join(mv) if mv else '静止'

    # 信号判定 (含翻市场纪律)
    kelly = value.get('kelly', 0) or 0
    best = value.get('best_direction', 'none')
    m_dir = max(('home', model['home_win']), ('draw', model['draw']), ('away', model['away_win']), key=lambda x: x[1])[0]
    k_dir = min(o.items(), key=lambda kv: kv[1])[0] if o else None
    flip = bool(o) and m_dir != k_dir
    if cold:
        verdict, vcls, why = '⛔ 拦截', 'no', '冷启动场次永不投注(市场即模型)'
    elif flip:
        verdict, vcls, why = '⛔ 拦截', 'no', f'翻市场纪律: 模型{ {"home":"主胜","draw":"平局","away":"客胜"}[m_dir] }{model[m_dir+"_win"]:.1%}≠市场({o[k_dir]:.2f}最低), 无翻市场资格'
    elif best == 'draw' and (post.get('draw', 0) or model.get('draw', 0)) < 0.35:
        verdict, vcls, why = '⛔ 拦截', 'no', '方向概率<35%自动反对(8月9日教训)'
    elif kelly < 0.01:
        verdict, vcls, why = '⛔ 无信号', 'no', f'Kelly={kelly:.1%}<1% 或 edge不足'
    else:
        verdict, vcls, why = '✅ 信号', 'yes', f'Kelly={kelly:.1%}'

    cards.append({
        'home': cn(p['home_team']), 'away': cn(p['away_team']),
        'league': LEAGUE_CN.get(p['league_code'], p['league_code']),
        'kickoff': m.get('kickoff_time', ''),
        'elo_h': p.get('elo_home', 0), 'elo_a': p.get('elo_away', 0),
        'cold_tag': cold_tag, 'cold_cls': cold_cls,
        'odds_h': o.get('home') or '无', 'odds_d': o.get('draw') or '无', 'odds_a': o.get('away') or '无',
        'handicap': m.get('handicap'), 'ah': ah,
        'ou': m.get('ou_line'), 'over': m.get('over_odds'), 'under': m.get('under_odds'),
        'mh': model.get('home_win', 0), 'md': model.get('draw', 0), 'ma': model.get('away_win', 0),
        'ph': post.get('home', model.get('home_win', 0)),
        'pd': post.get('draw', model.get('draw', 0)),
        'pa': post.get('away', model.get('away_win', 0)),
        'ou25': model.get('over_25'), 'ou35': model.get('over_35'), 'btts': model.get('btts'),
        'verdict': verdict, 'vcls': vcls, 'why': why, 'mv': mv_txt,
    })

n_cold = sum(1 for c in cards if c['cold_tag'] != '非冷')
n_sig = sum(1 for c in cards if c['vcls'] == 'yes')
n_flip = sum(1 for c in cards if '翻市场' in c['why'])

rows = []
for c in cards:
    rows.append(f'''
  <div class="card">
    <h3>{c['home']} vs {c['away']}<span class="t"> {c['league']} · 北京 {c['kickoff']} 开踢</span></h3>
    <div class="meta-line">
      <span class="badge {c['cold_cls']}">{c['cold_tag']}</span>
      <span>ELO {c['elo_h']:.0f} / {c['elo_a']:.0f}</span>
      <span>SPF {c['odds_h']} / {c['odds_d']} / {c['odds_a']}</span>
      <span>让球 {c['handicap']:+g} ({c['ah'].get('home')}/{c['ah'].get('draw')}/{c['ah'].get('away')})</span>
      <span>大{c['over']}/小{c['under']} (线{c['ou']})</span>
      <span>移动: {c['mv']}</span>
    </div>
    <div class="prob-line">
      <span>模型 主{c['mh']:.1%} / 平{c['md']:.1%} / 客{c['ma']:.1%}</span>
      <span class="dim">→ 后验 主{c['ph']:.1%} / 平{c['pd']:.1%} / 客{c['pa']:.1%}</span>
    </div>
    <div class="prob-line dim">
      <span>大2.5 {c['ou25']:.1%} · 大3.5 {c['ou35']:.1%} · 双方进球 {c['btts']:.1%}</span>
    </div>
    <div class="signal {c['vcls']}">{c['verdict']} — {c['why']}</div>
  </div>''')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>午盘更新 · 8月14日</title>
<style>
:root{{--bg:#0b0c10;--card:#13151d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;--purple:#a78bfa;--orange:#f0a838}}
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
.badge.cold{{background:rgba(248,81,73,0.12);color:var(--red)}}
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
  <h1>🌤️ 午盘更新 · 早盘→午盘对比<span style="font-size:0.7em;color:var(--purple);margin-left:8px">v3.1</span></h1>
  <sub>2026年8月14日 · 17场竞彩三线(SPF+让球+总进球) · 体彩实时赔率 · 早盘基线快照对比 · 开球18:00-03:15(北京)</sub>
</hdr>

<div class="kpi">
  <div class="k p"><div class="n">17</div><div class="lb">今日场次</div></div>
  <div class="k r"><div class="n">{n_cold}</div><div class="lb">冷启动</div></div>
  <div class="k"><div class="n">{17 - n_cold}</div><div class="lb">非冷启动</div></div>
  <div class="k g"><div class="n">{n_sig}</div><div class="lb">投注信号</div></div>
</div>

<div class="rule-box">
  <h3>⏰ 赔率移动对比 (早盘→午盘)</h3>
  <p>
    无任何场次移动超过10% · 仅4场微调3-8%: 特尔斯达主2.17→2.10 · 赫拉克勒斯主1.51→1.46(登博思4.35→4.71) · 敦刻尔克4.75→4.60<br>
    投注场次(埃尔夫斯堡)赔率 1.67→1.65 — <b>资金朝主胜方向流入, 顺移动确认方向, 稳定期维持</b>。<br>
    维度门禁: 1X2 ✅微弱 / OU35 ✅微弱 / OU25 ❌ / BTTS ❌ / AH ❌(13样本) — 未过门维度不产生信号。
  </p>
</div>
{''.join(rows)}

<div class="rule-box">
  <h3>📋 信号筛选结论 (1注)</h3>
  <p>
    <b>✅ 投注单:</b> 埃尔夫斯堡主胜 @1.65 Kelly=18% ¥440 (4.4%仓位) — 模型主71.3% vs 市场fair约53% · 与市场同向(主胜最低赔) · 非冷启动 · 1X2过门。<br>
    <b>⛔ 翻市场纪律拦截4场:</b> 东京绿茵(主42.7%vs客1.81) · 波鸿(客45.7%vs主2.38) · 罗森博格(主40.6%vs客2.25) · 赫拉克勒斯(客36.4%vs主1.46) — 模型方向≠市场方向且置信&lt;60%, 无翻市场资格(分歧胜率2-2)。<br>
    <b>🧊 冷启动6场禁注:</b> 沙特联3场(双冷1500/1500) + 荷乙2场(登博思/多德勒支无ELO) + 芬超1场(联赛画像冷)。<br>
    <b>🚫 维度门禁:</b> OU25 ❌(累计0.2562&gt;0.25) 全拦大小球 · AH 13样本未过门禁全拦让球 · BTTS ❌。<br>
    <b>早盘假冷修复已生效:</b> 柏太阳神/维京/埃尔夫斯堡/韦斯特罗斯4队名映射修复 → 3场转非冷, 罗森博格86.4%假edge异常消除(现40.6%与市场一致)。
  </p>
</div>

<div class="ftr">
  足球预测模型 v3.1 · 午盘更新 · 2026-08-14<br>
  ⚠ 仅供研究参考 · 理性购彩 · 不构成投注建议
</div>

</div></body></html>
'''

out = pathlib.Path(f'data/output/midday_analysis_{date_str}.html')
out.write_text(html, encoding='utf-8')
print(f'✅ 午盘报告已生成 → {out}')
