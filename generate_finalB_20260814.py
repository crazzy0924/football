# -*- coding: utf-8 -*-
"""生成终盘B HTML · 2026-08-14 · 晚场(>21:00)16场 · 1注埃尔夫斯堡 · EV门禁新上线拦7假edge · 6场>10%移动"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-14'
morning = json.loads(pathlib.Path('data/pinnacle_morning_2026-08-14.json').read_text('utf-8'))
now = json.loads(pathlib.Path(f'data/pinnacle_odds_{date_str}.json').read_text('utf-8'))
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))

from pipeline.reporter import TEAM_CN
def cn(name):
    return TEAM_CN.get(name, name)

def spf_map(data):
    m = {}
    for e in data:
        for bm in e.get('bookmakers', []):
            for mkt in bm['markets']:
                if mkt['key'] == 'h2h':
                    m[(e['home_team'], e['away_team'])] = {o['name']: o['price'] for o in mkt['outcomes']}
    return m
old, new = spf_map(morning), spf_map(now)

movers = []
for pair in sorted(new):
    if pair not in old:
        continue
    o, n = old[pair], new[pair]
    chgs, big = [], False
    for k in o:
        if k in n:
            chg = (n[k] - o[k]) / o[k] * 100
            if abs(chg) >= 2:
                arrow = '↑' if chg > 0 else '↓'
                chgs.append(f'{cn(k)}{o[k]}→{n[k]}({arrow}{abs(chg):.0f}%)')
                if abs(chg) >= 10:
                    big = True
    if chgs:
        movers.append({'home': cn(pair[0]), 'away': cn(pair[1]), 'chgs': chgs, 'big': big})

n_big = sum(1 for m in movers if m['big'])

mover_rows = []
for m in movers:
    tag = '<span style="color:var(--red)">>10%</span>' if m['big'] else ''
    mover_rows.append(f'<p>{m["home"]} vs {m["away"]}: {tag} ' + ' · '.join(m['chgs']) + '</p>')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘B · 8月14日 · 晚场(>21:00)</title>
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
.k.g .n{{color:var(--green)}}.k.r .n{{color:var(--red)}}.k.o .n{{color:var(--orange)}}.k.p .n{{color:var(--purple)}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-bottom:10px}}
.card h3{{font-size:0.9em;margin-bottom:6px}}.card h3 .t{{font-size:0.62em;color:var(--dim);font-weight:400}}
.meta-line{{display:flex;flex-wrap:wrap;gap:8px;font-size:0.68em;color:var(--dim);margin-bottom:4px}}
.signal{{display:inline-block;margin-top:6px;padding:3px 10px;border-radius:6px;font-size:0.7em;font-weight:700}}
.signal.yes{{background:rgba(63,185,80,0.1);color:var(--green)}}
.rule-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin:14px 0}}
.rule-box h3{{font-size:0.8em;color:var(--cyan);margin-bottom:6px}}
.rule-box p{{font-size:0.66em;color:var(--dim);line-height:1.7}}
.ftr{{text-align:center;padding:18px;color:var(--dim);font-size:0.55em;border-top:1px solid var(--border);margin-top:16px}}
</style>
</head>
<body><div class="c">

<hdr>
  <h1>🔵 终盘B · 晚场(>21:00开球)<span style="font-size:0.7em;color:var(--purple);margin-left:8px">v3.1</span></h1>
  <sub>2026年8月14日 22:37临场赔率 · 16场(23:00-03:15) · 三线合并 · EV门禁新上线 · 早盘→终盘B全天移动</sub>
</hdr>

<div class="kpi">
  <div class="k p"><div class="n">16</div><div class="lb">晚场场次</div></div>
  <div class="k g"><div class="n">1</div><div class="lb">投注信号</div></div>
  <div class="k o"><div class="n">7</div><div class="lb">EV门禁拦截</div></div>
  <div class="k r"><div class="n">{n_big}</div><div class="lb">&gt;10%移动场次</div></div>
  <div class="k"><div class="n">6</div><div class="lb">冷启动禁注</div></div>
</div>

<div class="card">
  <h3>🎫 投注单: 埃尔夫斯堡 vs 韦斯特罗斯<span class="t"> 瑞典超 · 北京 01:00 开踢</span></h3>
  <div class="meta-line">
    <span>胜平负 主胜 @1.57</span><span>Kelly(edge)=15%</span><span>¥372 (3.7%仓位)</span>
    <span>移动: 主1.67→1.57(-6%) · 客4.01→4.65(+16%) — 资金全天持续流向主队, 顺移确认</span>
  </div>
  <div class="meta-line"><span>模型主71.3% · 真实EV核验: 0.713×1.57=1.119 → +11.9% ✅</span><span>非冷启动 · 1X2过门 · 与市场同向</span></div>
  <div class="signal yes">✅ 维持下注 · 全天第4次确认(早盘¥457→午盘¥440→终盘A¥415→终盘B¥372, 仓位随edge收窄递减)</div>
</div>

<div class="rule-box">
  <h3>🛡️ EV门禁 (今日新上线 · 8月9日教训机械化) </h3>
  <p>
    旧Kelly=模型概率−去水公平概率(概率空间edge), 未用真实赔率 — 低赔大热时13%抽水全吃在热门上, 会放行真实EV为负的注。<br>
    新门禁: <b>模型概率×实际赔率必须>1</b>。今晚拦截7场假edge:<br>
    瓦萨主胜60.6%×1.61=0.976 · 内姆平局26.4%×3.75=0.989 · 罗森博格客胜40.6%×2.42=0.982 · 达曼平局29.2%×3.35=0.980 · 阿纳西主胜44.9%×2.16=0.971 · 兰斯主胜56.2%×1.68=0.944 · 里斯本竞技主胜80.0%×1.19=0.952(深盘让2球+ELO差402, 三重反对)。<br>
    幸存者核验: 埃尔夫斯堡 0.713×1.57=1.119 ✅ 真实价值。
  </p>
</div>

<div class="rule-box">
  <h3>📉 全天赔率移动 (早盘→终盘B)</h3>
  {''.join(mover_rows)}
  <p style="margin-top:6px">
    资金流向解读: 首轮状态驱动 — 不伦瑞克(6-1)/罗代兹(3-1)/敦刻尔克(4-2)全在吸金, 与模型(上季DC参数)方向大面积背离 · 模型指向处资金正在离开。<br>
    翻市场拦截2场(不伦瑞克客45.7%vs主2.18最低 · 赫拉克勒斯客36.4%vs主1.46) · 冷启动6场(沙特联3+荷乙2+芬超1)禁注 · OU25/AH/BTTS门禁全拦。
  </p>
</div>

<div class="ftr">
  足球预测模型 v3.1 · 终盘B · 2026-08-14<br>
  ⚠ 仅供研究参考 · 理性购彩 · 不构成投注建议
</div>

</div></body></html>
'''

out = pathlib.Path(f'data/output/finalB_analysis_{date_str}.html')
out.write_text(html, encoding='utf-8')
print(f'✅ 终盘B报告已生成 → {out}')
