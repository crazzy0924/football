"""生成午盘更新HTML报告 · 2026-08-11 · 全部完赛 · 终态汇总"""
import json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = '2026-08-11'
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))

# Actual results (from odds-api.io final scan)
ACTUAL = {
    'Mura Murska Sobota': (1, 3), 'POFC Botev Vratsa': (0, 3),
    'FC Fakel Voronezh': (0, 0), 'Västerås SK': (1, 0),
    'IK Sirius': (2, 2), 'Silkeborg IF': (1, 0),
    'Botev Plovdiv': (3, 2),
    'ACS Sepsi OSK Sfantu Gheorghe': (0, 0),
    'FC CFR 1907 Cluj': (0, 0), 'Plymouth Argyle': (2, 0),
    'Santa Clara': (2, 2), 'Audax Italiano': (2, 2),
}

TEAM_CN = {
    'IK Sirius': '天狼星', 'IF Brommapojkarna': '布鲁马波卡纳',
    'Västerås SK': '韦斯特罗斯', 'Djurgårdens IF': '佐加顿斯',
    'Santa Clara': '圣克拉拉', 'Nacional': '葡国民',
    'Audax Italiano': '奥达克斯意大利人', 'Nublense': '努布伦斯',
    'FC CFR 1907 Cluj': '克卢日', 'FC Universitatea Cluj': '克卢日大学',
    'Plymouth Argyle': '普利茅斯', 'Exeter City': '埃克塞特城',
    'Silkeborg IF': '锡尔克堡', 'Odense Boldklub': '欧登塞',
    'Mura Murska Sobota': '穆拉', 'NK Radomlje': '拉多姆利',
    'POFC Botev Vratsa': '博特夫弗拉察', 'PFC Slavia Sofia': '索菲亚斯拉维亚',
    'FC Fakel Voronezh': '沃罗涅日火炬', 'RFK Akhmat Grozny': '格罗兹尼',
    'Botev Plovdiv': '普罗夫迪夫博特夫', 'FK Spartak 1918 Varna': '瓦尔纳斯巴达',
    'ACS Sepsi OSK Sfantu Gheorghe': '圣格奥尔基塞普西', 'Fotbal Club FCSB': '布加勒斯特星',
}
LEAGUE_CN = {
    'SWE': '瑞典超', 'PPL': '葡超', 'CHI': '智利甲', 'ROM': '罗甲',
    'EFL': '英联杯', 'DEN': '丹超', 'SVN': '斯洛文甲', 'BUL': '保甲', 'RPL': '俄超',
}

def cn(n): return TEAM_CN.get(n, n)
def pct(v): return f'{v*100:.1f}%'

# ALREADY REVIEWED under Aug 10
AUG10_MATCHES = {('IK Sirius', 'IF Brommapojkarna'), ('Västerås SK', 'Djurgårdens IF'), ('Santa Clara', 'Nacional')}

total = len(preds)
cold_count = sum(1 for p in preds if p['cold_start'])
correct_pick = 0
correct_direction = 0  # non-draw direction correct
total_non_draw = 0
draw_total = 0
draw_correct = 0

rows = []
for p in preds:
    h = p['home_team']; a = p['away_team']
    m = p['model']; cs = p['cold_start']

    if h not in ACTUAL: continue
    hg, ag = ACTUAL[h]
    actual = 'draw' if hg == ag else ('home' if hg > ag else 'away')

    probs = {'home': m['home_win'], 'draw': m['draw'], 'away': m['away_win']}
    best_pick = max(probs, key=probs.get)
    hit = best_pick == actual

    if hit: correct_pick += 1
    if actual == 'draw':
        draw_total += 1
        if best_pick == 'draw': draw_correct += 1
    else:
        total_non_draw += 1
        if best_pick == actual: correct_direction += 1

    is_aug10 = (h, a) in AUG10_MATCHES
    rows.append({
        'home_cn': cn(h), 'away_cn': cn(a),
        'league': LEAGUE_CN.get(p['league_code'], p['league_code']),
        'score': f'{hg}-{ag}', 'actual': actual,
        'best': best_pick, 'hit': hit,
        'probs': (m['home_win'], m['draw'], m['away_win']),
        'cold': cs, 'aug10': is_aug10,
    })

acc = correct_pick / len(rows) if rows else 0
dir_acc = correct_direction / total_non_draw if total_non_draw else 0
draw_acc = draw_correct / draw_total if draw_total else 0
aug10_rows = [r for r in rows if r['aug10']]
aug11_rows = [r for r in rows if not r['aug10']]

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>午盘终态 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#14161d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:1000px;margin:0 auto}}
.header{{text-align:center;padding:28px 0 20px;border-bottom:1px solid var(--border);margin-bottom:20px}}
.header h1{{font-size:1.3em}}.header .sub{{color:var(--dim);font-size:0.8em;margin-top:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7em;margin-left:6px}}
.badge-v3{{background:#1a3a5c;color:var(--cyan)}}
.summary{{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}}
.si{{flex:1;min-width:90px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center}}
.si .n{{font-size:1.4em;font-weight:800}}.si .l{{font-size:0.6em;color:var(--dim);margin-top:2px}}
.si.good .n{{color:var(--green)}}.si.bad .n{{color:var(--red)}}

table{{width:100%;border-collapse:collapse;font-size:0.82em;margin:12px 0}}
th{{text-align:left;padding:8px 10px;border-bottom:2px solid var(--border);color:var(--dim);font-size:0.7em;text-transform:uppercase}}
td{{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.03)}}
tr.hit{{background:rgba(63,185,80,0.04)}}tr.miss{{background:rgba(248,81,73,0.03)}}
.pick-tag{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:0.7em;font-weight:600}}
.pick-h{{background:rgba(77,166,255,0.15);color:var(--home)}}
.pick-d{{background:rgba(139,143,163,0.15);color:var(--draw)}}
.pick-a{{background:rgba(240,168,56,0.15);color:var(--away)}}
.result{{font-weight:700;font-size:0.85em}}
.hit-mark{{color:var(--green)}}
.miss-mark{{color:var(--red)}}
.cold-dot{{color:#e879f9;font-size:0.65em}}
.aug10-tag{{font-size:0.55em;color:var(--dim);background:var(--border);padding:1px 5px;border-radius:3px;;margin-left:4px}}

.sec-title{{font-size:0.85em;font-weight:700;margin:20px 0 8px;color:var(--dim);border-bottom:1px solid var(--border);padding-bottom:6px}}
.odds-move{{display:inline-block;padding:2px 6px;border-radius:3px;font-size:0.65em;margin-left:4px}}
.move-up{{background:rgba(248,81,73,0.12);color:var(--red)}}
.move-down{{background:rgba(63,185,80,0.12);color:var(--green)}}

.footer{{text-align:center;padding:28px;color:var(--dim);font-size:0.7em;border-top:1px solid var(--border);margin-top:28px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🌤️ 午盘终态<span class="badge badge-v3">v3.0</span></h1>
  <div class="sub">{date_str} · 全部12场已完赛 · 终态汇总 · 赔率无变动(仅1场早盘有赔率)</div>
</div>

<div class="summary">
  <div class="si"><div class="n">{len(rows)}</div><div class="l">总场次</div></div>
  <div class="si bad"><div class="n">{correct_pick}/{len(rows)}</div><div class="l">1X2准确率</div></div>
  <div class="si"><div class="n">{draw_correct}/{draw_total}</div><div class="l">平局命中</div></div>
  <div class="si"><div class="n">{correct_direction}/{total_non_draw}</div><div class="l">非平局方向</div></div>
  <div class="si"><div class="n">{cold_count}</div><div class="l">冷启动</div></div>
</div>

<div class="sec-title">⚽ 新比赛 (8月11日 · {len(aug11_rows)}场 · 冷启动{sum(1 for r in aug11_rows if r['cold'])}场)</div>
<table>
<tr><th>比赛</th><th>联赛</th><th>比分</th><th>模型预测</th><th>最佳</th><th>结果</th></tr>
'''
for r in aug11_rows:
    hit_cls = 'hit' if r['hit'] else 'miss'
    mark = '✅' if r['hit'] else '❌'
    ph, pd, pa = r['probs']
    pick_cls = {'home': 'pick-h', 'draw': 'pick-d', 'away': 'pick-a'}[r['best']]
    cold_str = ' 🧊' if r['cold'] else ''
    html += f'''<tr class="{hit_cls}">
  <td>{r['home_cn']} vs {r['away_cn']}{cold_str}</td>
  <td style="font-size:0.7em;color:var(--dim)">{r['league']}</td>
  <td class="result">{r['score']}</td>
  <td style="font-size:0.75em">{pct(ph)}/{pct(pd)}/{pct(pa)}</td>
  <td><span class="pick-tag {pick_cls}">{r['best']}</span></td>
  <td class="{'hit-mark' if r['hit'] else 'miss-mark'}">{mark}</td>
</tr>\n'''

html += '''</table>

<div class="sec-title">🔄 昨日延续 (8月10日预测 · 3场 · 已独立复盘)</div>
<table>
<tr><th>比赛</th><th>联赛</th><th>比分</th><th>模型预测</th><th>最佳</th><th>结果</th></tr>
'''
for r in aug10_rows:
    hit_cls = 'hit' if r['hit'] else 'miss'
    mark = '✅' if r['hit'] else '❌'
    ph, pd, pa = r['probs']
    pick_cls = {'home': 'pick-h', 'draw': 'pick-d', 'away': 'pick-a'}[r['best']]
    html += f'''<tr class="{hit_cls}">
  <td>{r['home_cn']} vs {r['away_cn']}<span class="aug10-tag">8/10</span></td>
  <td style="font-size:0.7em;color:var(--dim)">{r['league']}</td>
  <td class="result">{r['score']}</td>
  <td style="font-size:0.75em">{pct(ph)}/{pct(pd)}/{pct(pa)}</td>
  <td><span class="pick-tag {pick_cls}">{r['best']}</span></td>
  <td class="{'hit-mark' if r['hit'] else 'miss-mark'}">{mark}</td>
</tr>\n'''

html += '''</table>
'''

# Odds movement section - N/A since only 1 match had odds
html += '''
<div class="sec-title">📊 赔率移动 (早盘→午盘)</div>
<p style="font-size:0.78em;color:var(--dim);padding:8px 0">
  ⚠ 无赔率移动对比 — 今日仅1场(Audax Italiano vs Nublense)早盘时有Kambi赔率，且为进行中状态，赔率随比赛进程实时变动。
  其余11场全程无赔率数据(the-odds-api.com配额耗尽 + odds-api.io Kambi/Unibet未开盘)。
</p>
'''

# Overall diagnostics
html += f'''
<div class="sec-title">🔍 午盘诊断</div>
<table>
<tr><th>指标</th><th>早盘</th><th>午盘(终态)</th><th>变化</th></tr>
<tr><td>总场次</td><td>12</td><td>12</td><td>—</td></tr>
<tr><td>未开赛</td><td>1 (Cluj)</td><td>0</td><td>全完赛</td></tr>
<tr><td>进行中</td><td>1 (Audax)</td><td>0 (2-2完赛)</td><td>完结</td></tr>
<tr><td>有赔率场次</td><td>1</td><td>0 (全部settled)</td><td>—</td></tr>
<tr><td>投注信号</td><td>0</td><td>0</td><td>—</td></tr>
</table>
<p style="font-size:0.75em;color:var(--dim);margin-top:10px">
  今日9场新比赛均为冷启动(联赛均值攻防)，模型未产生有价值信号。核心结论：<b>API配额恢复前，非核心联赛(瑞典超/葡超/五大之外的联赛)预测均为盲猜，不建议下注。</b>
</p>
'''

html += f'''
<div class="footer">
  足球预测模型 v3.0 · 午盘终态 {date_str} · 全部完赛<br>
  API状态: the-odds-api.com 500/500耗尽 · odds-api.io Kambi+Unibet仅2家 · 11/12场无赔率数据
</div>
</div></body></html>'''

out_path = pathlib.Path(f'data/output/midday_analysis_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'午盘报告: {out_path}')
print(f'新比赛 {len(aug11_rows)}场 · 准确率 {correct_pick}/{len(rows)} · 冷启动 {cold_count}场')
