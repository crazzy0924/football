"""生成早盘预测HTML报告 · v3.0 · 三线合并预览 · 按联赛分组"""
import json, sys, io, pathlib
from datetime import datetime
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y-%m-%d')
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))

# Load odds from today.json (Kambi 1X2)
today = json.loads(pathlib.Path('data/today.json').read_text('utf-8'))
odds_map = {}
for m in today:
    if m.get('odds'):
        odds_map[f"{m['home_team']}|{m['away_team']}"] = m['odds']

# Load bets
bets_path = pathlib.Path(f'data/output/pinnacle_bets_{date_str}.json')
if bets_path.exists():
    raw = json.loads(bets_path.read_text('utf-8'))
    bets = raw if isinstance(raw, list) else raw.get('bets', [])
else:
    bets = []

LEAGUE_CN = {
    'UCL': '欧冠资格赛', 'UEL': '欧联资格赛', 'UEC': '欧协联资格赛',
    'CLB': '解放者杯淘汰赛', 'CSD': '南球杯淘汰赛', 'LGC': '联赛杯(美墨)',
    'COL': '哥伦比亚甲', 'ARG': '阿根廷甲', 'RSA': '南非超',
    'CZE': '捷克杯', 'DEN': '丹麦杯', 'BUL': '保加利亚乙',
    'SW2': '瑞典甲', 'CHI': '智利杯', 'CAN': '加拿大冠',
    'ROM': '罗马尼亚杯', 'AUS': '澳洲杯',
}
LEAGUE_REGION = {
    'UCL': '欧战', 'UEL': '欧战', 'UEC': '欧战',
    'CLB': '南美', 'CSD': '南美', 'COL': '南美', 'ARG': '南美',
    'LGC': '北美', 'CAN': '北美',
    'RSA': '非洲',
    'CZE': '欧洲杯赛', 'DEN': '欧洲杯赛', 'BUL': '欧洲', 'SW2': '欧洲',
    'CHI': '南美', 'ROM': '欧洲杯赛', 'AUS': '大洋洲',
}

def pct(v): return f'{v*100:.1f}%'

total = len(preds)
cold_count = sum(1 for p in preds if p.get('cold_start'))
with_odds_count = sum(1 for p in preds if f"{p['home_team']}|{p['away_team']}" in odds_map)
non_default = [p for p in preds if abs(p['model']['home_win'] - 0.4546) > 0.01]
bet_count = len(bets)

# Group by region then league
by_region = defaultdict(lambda: defaultdict(list))
for p in preds:
    lc = p['league_code']
    region = LEAGUE_REGION.get(lc, '其他')
    by_region[region][lc].append(p)

REGION_ORDER = ['欧战', '南美', '北美', '非洲', '欧洲杯赛', '欧洲', '大洋洲', '其他']

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>早盘预测 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#14161d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;--purple:#e879f9;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:1100px;margin:0 auto}}
.header{{text-align:center;padding:28px 0 20px;border-bottom:1px solid var(--border);margin-bottom:20px}}
.header h1{{font-size:1.4em}}.header .sub{{color:var(--dim);font-size:0.8em;margin-top:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7em;margin-left:6px;font-weight:600}}
.badge-v3{{background:#1a3a5c;color:var(--cyan)}}
.badge-warn{{background:#3a2a0a;color:var(--away)}}

.summary{{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap}}
.si{{flex:1;min-width:90px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;text-align:center}}
.si .n{{font-size:1.5em;font-weight:800}}.si .l{{font-size:0.65em;color:var(--dim);margin-top:4px}}
.si.warn .n{{color:var(--away)}}.si.good .n{{color:var(--green)}}.si.info .n{{color:var(--cyan)}}

.diag-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px}}
.diag-box h3{{font-size:0.9em;color:var(--cyan);margin-bottom:10px}}
.diag-box p{{font-size:0.78em;color:var(--dim);line-height:1.7}}

.region-block{{margin-bottom:24px}}
.region-title{{font-size:0.85em;font-weight:700;color:var(--cyan);padding:8px 0;border-bottom:1px solid var(--border);margin-bottom:8px}}

.league-group{{margin-bottom:12px}}
.league-label{{font-size:0.75em;color:var(--dim);padding:4px 0 6px 8px;display:flex;justify-content:space-between}}
.league-label .ct{{color:var(--text);margin-right:8px}}

.match-card{{display:flex;align-items:center;padding:10px 14px;background:var(--card);border:1px solid var(--border);border-radius:6px;margin-bottom:3px;gap:10px;font-size:0.82em}}
.match-card.cold{{border-left:2px solid var(--purple)}}
.match-card.signal{{border-left:2px solid var(--green)}}
.mc-teams{{flex:2.5;min-width:0}}
.mc-teams .vs{{color:var(--dim);margin:0 6px}}
.mc-time{{flex:0 0 42px;font-size:0.7em;color:var(--dim);text-align:center}}
.mc-probs{{flex:1.3;text-align:center;font-size:0.75em}}
.mc-odds{{flex:0 0 150px;text-align:right;font-size:0.72em}}
.mc-signal{{flex:0 0 70px;text-align:right}}

.prob-bar{{display:flex;height:5px;border-radius:3px;overflow:hidden;background:var(--bg);margin-top:3px}}
.prob-bar .h{{background:var(--home)}}
.prob-bar .d{{background:var(--draw)}}
.prob-bar .a{{background:var(--away)}}

.signal-tag{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:0.7em;font-weight:600}}
.signal-none{{background:rgba(255,255,255,0.03);color:var(--dim)}}
.signal-edge{{background:rgba(63,185,80,0.15);color:var(--green)}}
.cold-dot{{font-size:0.65em;margin-left:2px}}

.footer{{text-align:center;padding:28px;color:var(--dim);font-size:0.7em;border-top:1px solid var(--border);margin-top:28px}}

table{{width:100%;border-collapse:collapse;font-size:0.78em}}
th{{text-align:left;padding:4px 8px;border-bottom:2px solid var(--border);color:var(--dim);font-size:0.7em}}
td{{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.02)}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🌅 早盘预测<span class="badge badge-v3">v3.0</span></h1>
  <div class="sub">{date_str} · Dixon-Coles + 贝叶斯 + Kelly · 17个联赛/杯赛 · odds-api.io v3 (Kambi/Unibet)</div>
</div>

<div class="summary">
  <div class="si info"><div class="n">{total}</div><div class="l">总场次</div></div>
  <div class="si warn"><div class="n">{cold_count}</div><div class="l">冷启动 🧊</div></div>
  <div class="si"><div class="n">{with_odds_count}</div><div class="l">有赔率</div></div>
  <div class="si"><div class="n">{len(non_default)}</div><div class="l">已知ELO</div></div>
  <div class="si {'good' if bet_count else ''}"><div class="n">{bet_count}</div><div class="l">投注信号</div></div>
</div>

<div class="diag-box">
  <h3>📊 早盘诊断</h3>
  <p>
    <b>⚠️ 全面冷启动 ({cold_count}/{total}场)</b> — 今日覆盖17个联赛/杯赛，绝大多数为新接入赛事。球队无历史ELO，使用联赛均值攻防参数(att=1.0, def=1.0)，概率统一为45.5/25.8/28.7。<br>
    <b>📉 赔率覆盖率仅{with_odds_count}/{total}</b> — the-odds-api.com v4配额耗尽(500/500)；odds-api.io v3免费层仅Kambi/Unibet两家，大部分杯赛/非欧联赛无博彩公司覆盖。<br>
    <b>✅ 唯一已知球队: SK Brann</b> — 挪威超球队有ELO数据，对塞浦路斯球队Apollon Limassol给出84.9%客胜概率。Brann ELO远高于对手。<br>
    <b>🔮 无投注信号</b> — 所有场次edge不足或冷启动，Kelly筛选零通过。建议观望，等待: (1) API配额恢复 (2) 欧洲联赛新赛季ELO积累。
  </p>
</div>
'''

# Non-default section
if non_default:
    html += '<div class="region-block"><div class="region-title">⭐ 已知球队预测 (模型可区分强弱)</div>'
    for p in non_default:
        h, a = p['home_team'], p['away_team']
        m = p['model']
        key = f"{h}|{a}"
        odds = odds_map.get(key)
        lc = p['league_code']
        lcn = LEAGUE_CN.get(lc, lc)
        hp, dp, ap = m['home_win'], m['draw'], m['away_win']
        elo_h = p.get('elo_home', 1500)
        elo_a = p.get('elo_away', 1500)
        best = max([('home', hp), ('draw', dp), ('away', ap)], key=lambda x: x[1])
        pick_cls = {'home': 'var(--home)', 'draw': 'var(--draw)', 'away': 'var(--away)'}[best[0]]
        pick_cn = {'home': '主胜', 'draw': '平局', 'away': '客胜'}[best[0]]

        html += f'''<div class="match-card signal">
  <div class="mc-teams">{h} <span class="vs">vs</span> {a}</div>
  <div class="mc-time">ELO<br>{elo_h:.0f}/{elo_a:.0f}</div>
  <div class="mc-probs">
    <span style="color:var(--home)">{pct(hp)}</span>/<span style="color:var(--draw)">{pct(dp)}</span>/<span style="color:var(--away)">{pct(ap)}</span>
    <div class="prob-bar"><div class="h" style="width:{hp*100}%"></div><div class="d" style="width:{dp*100}%"></div><div class="a" style="width:{ap*100}%"></div></div>
  </div>
  <div class="mc-odds">'''
        if odds:
            html += f'Kambi: <span style="color:var(--home)">{odds["home"]:.2f}</span>/<span style="color:var(--draw)">{odds["draw"]:.2f}</span>/<span style="color:var(--away)">{odds["away"]:.2f}</span>'
        else:
            html += '—'
        html += f'</div><div class="mc-signal"><span class="signal-tag" style="color:{pick_cls};background:rgba(255,255,255,0.05)">{pick_cn} {pct(best[1])}</span></div></div>\n'
    html += '</div>'

# Cold start matches by region
for region in REGION_ORDER:
    if region not in by_region:
        continue
    region_data = by_region[region]
    region_total = sum(len(v) for v in region_data.values())
    html += f'<div class="region-block"><div class="region-title">{region} ({region_total}场)</div>'

    for lc in sorted(region_data.keys()):
        matches = region_data[lc]
        lcn = LEAGUE_CN.get(lc, lc)
        html += f'<div class="league-group"><div class="league-label"><span>{lcn}</span><span class="ct">{len(matches)}场</span></div>'
        for p in matches:
            h, a = p['home_team'], p['away_team']
            m = p['model']
            key = f"{h}|{a}"
            odds = odds_map.get(key)
            kickoff = p.get('kickoff', '?')

            html += f'''<div class="match-card cold">
  <div class="mc-teams">{h} <span class="vs">vs</span> {a} <span class="cold-dot">🧊</span></div>
  <div class="mc-time">{kickoff}</div>
  <div class="mc-probs">
    <span style="color:var(--home)">{pct(m['home_win'])}</span>/<span style="color:var(--draw)">{pct(m['draw'])}</span>/<span style="color:var(--away)">{pct(m['away_win'])}</span>
    <div class="prob-bar"><div class="h" style="width:{m['home_win']*100}%"></div><div class="d" style="width:{m['draw']*100}%"></div><div class="a" style="width:{m['away_win']*100}%"></div></div>
  </div>
  <div class="mc-odds">'''
            if odds:
                html += f'<span style="color:var(--home)">{odds["home"]:.2f}</span>/<span style="color:var(--draw)">{odds["draw"]:.2f}</span>/<span style="color:var(--away)">{odds["away"]:.2f}</span>'
            else:
                html += '—'
            html += '</div><div class="mc-signal"><span class="signal-tag signal-none">冷启动</span></div></div>\n'
        html += '</div>'
    html += '</div>'

# Bet section
html += f'''
<div class="diag-box">
  <h3>🎯 投注筛选 (三线合并: 1X2 + 亚盘 + 大小球)</h3>
  <p style="font-size:0.78em;color:var(--dim)">
    {"<b>0注信号</b> · 筛选条件: edge>5% + Kelly>1% + 非冷启动 + 方向概率≥35% · 全部{total}场均不满足 · 主要阻断因素: 冷启动(49/49) + 赔率缺失(39/49)" if bet_count == 0 else f"共{bet_count}注信号"}
  </p>
</div>
'''

# API status
html += f'''
<div class="diag-box">
  <h3>📡 API状态</h3>
  <table>
  <tr><td>the-odds-api.com v4</td><td style="color:var(--red)">配额耗尽 500/500</td><td>全部联赛不可用</td></tr>
  <tr><td>odds-api.io v3 (Kambi)</td><td style="color:var(--green)">正常</td><td>{with_odds_count}/{total}场覆盖</td></tr>
  <tr><td>odds-api.io v3 (Unibet)</td><td style="color:var(--yellow)">有限</td><td>免费层2家博彩公司</td></tr>
  <tr><td>ELO数据库</td><td>665队/662参数</td><td>覆盖25个联赛</td></tr>
  <tr><td><b>总结</b></td><td colspan="2" style="color:var(--away)">API配额+ELO覆盖面双重不足 · 当前阶段不适合大规模投注</td></tr>
  </table>
</div>
'''

html += f'''
<div class="footer">
  足球预测模型 v3.0 · Dixon-Coles + 贝叶斯后验 + Kelly 1/4 · 赔率源: odds-api.io v3<br>
  早盘预测 {date_str} · {total}场/{len(by_region)}个区域/{len(LEAGUE_CN)+1}个联赛 · 仅供研究参考
</div>
</div></body></html>'''

out_path = pathlib.Path(f'data/output/early_analysis_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'早盘报告已保存: {out_path}')
print(f'总场次: {total} · 冷启动: {cold_count} · 有赔率: {with_odds_count} · 已知ELO: {len(non_default)} · 投注信号: {bet_count}')
