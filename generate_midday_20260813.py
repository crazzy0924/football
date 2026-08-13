"""生成午盘更新HTML · 2026-08-13 · 首拉基线 (10场三线) · 0注信号"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-13'
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))

from pipeline.reporter import TEAM_CN

LEAGUE_CN = {'UEL': '欧罗巴资格赛', 'SPL': '沙特联', 'CLB': '解放者杯', 'UCL': '欧超杯', 'CSD': '南球杯'}

def cn(name):
    return TEAM_CN.get(name, name)

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

    # 信号判定
    kelly = value.get('kelly', 0) or 0
    best = value.get('best_direction', 'none')
    edge_max = max(value.get('home_edge', 0), value.get('draw_edge', 0), value.get('away_edge', 0))
    if cold:
        verdict, vcls, why = '⛔ 拦截', 'no', '冷启动场次永不投注(市场即模型)'
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
        'odds_h': o.get('home'), 'odds_d': o.get('draw'), 'odds_a': o.get('away'),
        'handicap': m.get('handicap'), 'ah': ah,
        'ou': m.get('ou_line'), 'over': m.get('over_odds'), 'under': m.get('under_odds'),
        'mh': model.get('home_win', 0), 'md': model.get('draw', 0), 'ma': model.get('away_win', 0),
        'ph': post.get('home', model.get('home_win', 0)),
        'pd': post.get('draw', model.get('draw', 0)),
        'pa': post.get('away', model.get('away_win', 0)),
        'ou25': model.get('over_25'), 'ou35': model.get('over_35'), 'btts': model.get('btts'),
        'verdict': verdict, 'vcls': vcls, 'why': why,
    })

n_cold = sum(1 for c in cards if c['cold_tag'] != '非冷')
n_sig = sum(1 for c in cards if c['vcls'] == 'yes')

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
<title>午盘更新 · 8月13日</title>
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
  <h1>🌤️ 午盘更新 · 首拉基线<span style="font-size:0.7em;color:var(--purple);margin-left:8px">v3.1</span></h1>
  <sub>2026年8月13日 · 10场竞彩三线(SPF+让球+总进球) · 体彩实时赔率 · 开球时间均为8月14日凌晨(北京时间)</sub>
</hdr>

<div class="kpi">
  <div class="k p"><div class="n">10</div><div class="lb">今日场次</div></div>
  <div class="k r"><div class="n">{n_cold}</div><div class="lb">冷启动</div></div>
  <div class="k"><div class="n">{10 - n_cold}</div><div class="lb">非冷启动</div></div>
  <div class="k g"><div class="n">{n_sig}</div><div class="lb">投注信号</div></div>
</div>

<div class="rule-box">
  <h3>⏰ 首拉基线说明</h3>
  <p>
    今日为首次赔率拉取（无早盘快照），本报告即今日基线。赔率移动>10%的场次标注从<b>下一次拉取</b>开始生效。<br>
    全部10场开球时间在北京时间8月14日 00:15–08:30 → 全部属于<b>终盘B（>21:00晚场）</b>范畴，投注截止在今晚。<br>
    维度门禁状态: 1X2 ✅微弱 / OU35 ✅微弱 / OU25 ❌ / BTTS ❌ / AH ❌(3样本) — 未过门维度不产生信号。
  </p>
</div>
{''.join(rows)}

<div class="rule-box">
  <h3>📋 信号筛选结论 (0注)</h3>
  <p>
    <b>1X2:</b> 唯一非冷启动且有edge的场次 — 哈茨vs本菲卡, 平局edge +10.1%、Kelly 2.4%, 但平局方向概率仅28.6% &lt; 35% → <b>自动反对</b>(8月9日教训: 方向概率&lt;35%不下注)。其余: 8场冷启动禁注 + Kelly不足。<br>
    <b>OU25/OU35/BTTS:</b> 维度门禁未过(累计Brier &gt; 气候基线) → 禁注。仅记录观察: 雷克雅未克维京人vs图恩 模型大2.5 70.1% vs 市场65.1% — 列入观察, 不投注。<br>
    <b>AH让球:</b> 3样本未过门禁 → 禁注。(技术债: 让球edge分析器market_implied占位1/3未读入体彩HHAD赔率, 待修)<br>
    <b>市场参考纪律:</b> 8场冷启动模型λ全部由体彩赔率反推(KL最小化), 冷启动场次只作方向锚, 不作edge来源。
  </p>
</div>

<div class="ftr">
  足球预测模型 v3.1 · 午盘首拉 · 2026-08-13<br>
  ⚠ 仅供研究参考 · 理性购彩 · 不构成投注建议
</div>

</div></body></html>
'''

out = pathlib.Path(f'data/output/midday_analysis_{date_str}.html')
out.write_text(html, encoding='utf-8')
print(f'✅ 午盘报告已生成 → {out}')
