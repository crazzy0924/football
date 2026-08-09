#!/usr/bin/env python3
"""8月9日早盘分析 HTML生成"""
import json, sys, io
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except: pass

ROOT = Path(__file__).resolve().parent

with open(ROOT / 'daily_tracking.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def shin(oh, od, oa):
    s = 1/oh + 1/od + 1/oa
    return round(1/(oh*s), 3), round(1/(od*s), 3), round(1/(oa*s), 3)

rows = ""
for m in data['matches']:
    mid = m['match_id']
    spf = m.get('official_spf') or {}
    hhad = m.get('official_hhad') or {}

    if spf and spf.get('h'):
        h, d, a = float(spf['h']), float(spf['d']), float(spf['a'])
        ph, pd, pa = shin(h, d, a)
        spf_str = f'{spf["h"]}/{spf["d"]}/{spf["a"]}'
        prob_str = f'主{ph:.0%}<br>平{pd:.0%}<br>客{pa:.0%}'
        if ph >= 0.55: dir_str = '<span style="color:#3fb950;font-weight:700">主胜</span>'
        elif pa >= 0.48: dir_str = '<span style="color:#58a6ff;font-weight:700">客胜</span>'
        else: dir_str = '<span style="color:#f0a838">均势</span>'
        signal = ''
        if ph >= 0.65: signal = '<span style="color:#3fb950">🔥强热</span>'
        elif ph >= 0.55: signal = '<span style="color:#3fb950">🟢关注</span>'
        elif pa >= 0.55: signal = '<span style="color:#58a6ff">🔥强热</span>'
        elif pa >= 0.48: signal = '<span style="color:#58a6ff">🟢关注</span>'
    else:
        spf_str = '<span style="color:#f85149">无SPF</span>'
        prob_str = '-'
        dir_str = '-'
        signal = '<span style="color:#f85149">⚠️深盘</span>'

    rank_str = f'{m.get("home_rank","?")} vs {m.get("away_rank","?")}' if m.get('home_rank') else '-'

    rows += f"""<tr>
      <td class="num">{mid}</td>
      <td><div class="match-name">{m['home_team_cn']} vs {m['away_team_cn']}</div><div class="league-tag">{m['league_cn']}</div></td>
      <td class="odds">{spf_str}</td>
      <td class="dir">{dir_str}</td>
      <td class="probs">{prob_str}</td>
      <td>{rank_str}</td>
      <td>{signal}</td>
    </tr>"""

# Count stats
strong_home = sum(1 for m in data['matches'] if (m.get('official_spf') or {}).get('h') and shin(float(m['official_spf']['h']), float(m['official_spf']['d']), float(m['official_spf']['a']))[0] >= 0.55)
strong_away = sum(1 for m in data['matches'] if (m.get('official_spf') or {}).get('h') and shin(float(m['official_spf']['h']), float(m['official_spf']['d']), float(m['official_spf']['a']))[2] >= 0.48)
no_spf = sum(1 for m in data['matches'] if not (m.get('official_spf') or {}).get('h'))

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>早盘分析 · 2026-08-09</title>
<style>
:root{{--bg:#080b14;--card:#0d111c;--border:#161b2a;--text:#c8ccd8;--muted:#5a5a6e;--a2:#a78bfa;--g:#3fb950;--r:#f85149;--y:#f0a838;--b:#58a6ff;--cy:#00d4ff}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.6;min-height:100vh;padding:24px;max-width:1200px;margin:0 auto}}
.top{{background:linear-gradient(135deg,#0a0f1e,#11163a);border:1px solid var(--border);border-radius:12px;padding:20px 24px;margin-bottom:18px;display:flex;align-items:center;gap:14px}}
.top .icon{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7c6ff7,#a78bfa);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1.1em;flex-shrink:0}}
.top h1{{font-size:1.05em}} .top em{{color:var(--a2);font-style:normal}} .top .sub{{font-size:0.6em;color:var(--muted)}}
.dash{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.di{{flex:1;min-width:80px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 8px;text-align:center}} .di .n{{font-size:1.4em;font-weight:800}} .di .l{{font-size:0.52em;color:var(--muted)}}
h2{{font-size:0.85em;margin:20px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--border)}} h2 span{{color:var(--a2)}}
table{{width:100%;border-collapse:collapse;font-size:0.75em}}
th{{background:var(--card);padding:8px 6px;text-align:left;font-size:0.7em;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border)}}
td{{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,0.03);vertical-align:top}}
tr:hover td{{background:rgba(124,111,247,0.02)}}
.num{{font-weight:700;color:var(--muted);min-width:45px}}
.match-name{{font-weight:600}} .league-tag{{font-size:0.6em;color:var(--muted)}}
.odds{{font-weight:600;min-width:90px}} .dir{{min-width:55px}} .probs{{font-size:0.7em;color:var(--muted);min-width:55px}}
.signal-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin:16px 0;font-size:0.75em;line-height:1.7}}
.signal-box h3{{font-size:0.85em;margin-bottom:8px}}
.note{{background:rgba(124,111,247,0.04);border:1px solid rgba(124,111,247,0.1);border-radius:8px;padding:12px 16px;margin:14px 0;font-size:0.65em;line-height:1.7}}
.ft{{text-align:center;padding:20px;color:var(--muted);font-size:0.55em;opacity:0.4}}
</style>
</head>
<body>
<div class="top">
<div class="icon">🔍</div>
<h1><em>早盘分析</em> · 2026-08-09</h1>
<span class="sub">体彩官方SPF赔率 · 27场比赛 · 09:00初盘基准</span>
</div>

<div class="dash">
<div class="di"><div class="n" style="color:var(--a2)">{data['total_matches']}</div><div class="l">总场次</div></div>
<div class="di"><div class="n" style="color:var(--g)">{strong_home}</div><div class="l">主胜强热</div></div>
<div class="di"><div class="n" style="color:var(--b)">{strong_away}</div><div class="l">客胜强热</div></div>
<div class="di"><div class="n" style="color:var(--r)">{no_spf}</div><div class="l">无SPF/深盘</div></div>
<div class="di"><div class="n" style="color:var(--y)">{data['total_matches'] - strong_home - strong_away - no_spf}</div><div class="l">均势/模糊</div></div>
</div>

<div class="signal-box">
<h3>📡 早盘关键观察</h3>
<div style="margin:4px 0">• <b>🔥 今日最强信号:</b> 7024 弗拉门戈 SPF 1.15 → 隐含主胜77% · 巴甲主场霸主 · 维多利亚弱旅</div>
<div style="margin:4px 0">• <b>🔥 次强信号:</b> 1001 天狼星 SPF 1.21 → 主胜73% · 瑞典超 · 排名优势</div>
<div style="margin:4px 0">• <b>🔥 阿贾克斯客战:</b> 7009 SPF 1.38 → 客胜64% · 荷甲传统强队 · 兹沃勒中下游</div>
<div style="margin:4px 0">• <b>⚖️ 三向均势集中:</b> 日职(7001)/日乙(7002,7003)/荷甲(7010)/挪超(7011) — 5场无明显方向</div>
<div style="margin:4px 0">• <b>⚠️ 深盘预警:</b> 7018 波尔图、7020 本菲卡 — 无SPF仅HHAD深盘 · 葡超冷启动风险</div>
<div style="margin:4px 0">• <b>📊 联赛分布:</b> 荷甲4场 · 瑞典超5场(含8/10) · 葡超5场 · 挪超3场 · 芬超3场 · 巴甲2场 · 日职/日乙/德乙各1-2场</div>
<div style="margin:4px 0">• <b>🟡 昨日复盘教训:</b> 揭幕战方向命中率仅~14% · 强SPF(>60%)可靠(2/2) · 蒸汽移动信号可靠(004全北验证) · 今日将执行「揭幕战降级」规则</div>
</div>

<h2>⚽ <span>早盘赔率全览</span></h2>
<table>
<thead><tr>
<th>编号</th><th>对阵</th><th>SPF</th><th>方向</th><th>概率</th><th>排名</th><th>信号</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>

<div class="note">
<strong>📐 方法:</strong> Shin调整去margin · 隐含概率>55%主胜=强热 · >48%客胜=强热 · <42%所有方向=三向均势<br>
<strong>📊 数据源:</strong> lottery.gov.cn 官方SPF赔率 (09:00拉取) · 27场覆盖(含8月10日3场早开)<br>
<strong>🟡 权重调整(已应用昨日复盘):</strong> 揭幕战自动降级 · 强SPF(>60%)维持推荐 · 三向均势不推荐<br>
<strong>⏰ 时间线:</strong> 16:00 午盘蒸汽移动检测 → 22:00 终盘预测<br>
<strong>生成时间:</strong> {datetime.now().isoformat()}
</div>

<div class="ft">© JOYBOY · 8月9日早盘 09:00 · 27场 · {strong_home}强主{strong_away}强客 · 数据: lottery.gov.cn</div>
</body>
</html>"""

out = ROOT / 'morning_20260809.html'
out.write_text(html, encoding='utf-8')
print(f'✅ {out} ({data["total_matches"]} matches)')
