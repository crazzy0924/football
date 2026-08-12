"""生成午盘更新HTML · 2026-08-12 · 赔率API双瘫痪 · 0变动"""
import json, sys, io, pathlib
from datetime import datetime
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = sys.argv[1] if len(sys.argv) > 1 else '2026-08-12'
preds = json.loads(pathlib.Path(f'data/output/predictions_{date_str}.json').read_text('utf-8'))

LEAGUE_CN = {
    'UCL': '欧冠资格赛', 'UEL': '欧联资格赛', 'UEC': '欧协联资格赛',
    'CLB': '解放者杯', 'CSD': '南球杯', 'LGC': '联赛杯(美墨)',
    'COL': '哥伦比亚甲', 'ARG': '阿根廷甲', 'RSA': '南非超',
    'CZE': '捷克杯', 'DEN': '丹麦杯', 'BUL': '保加利亚乙',
    'SW2': '瑞典甲', 'CHI': '智利杯', 'CAN': '加拿大冠',
    'ROM': '罗马尼亚杯', 'AUS': '澳洲杯',
}
REGION = {
    'UCL': '欧战', 'UEL': '欧战', 'UEC': '欧战',
    'CLB': '南美', 'CSD': '南美', 'COL': '南美', 'ARG': '南美',
    'LGC': '北美', 'CAN': '北美', 'RSA': '非洲',
    'CZE': '欧洲杯赛', 'DEN': '欧洲杯赛', 'BUL': '欧洲', 'SW2': '欧洲',
    'CHI': '南美', 'ROM': '欧洲杯赛', 'AUS': '大洋洲',
}

total = len(preds)
cold = sum(1 for p in preds if p.get('cold_start'))
non_default = [p for p in preds if abs(p['model']['home_win'] - 0.4546) > 0.01]

# League distribution
by_league = defaultdict(list)
for p in preds:
    by_league[p['league_code']].append(p)

# Check kickoff times for "已开赛" vs "未开赛"
from datetime import datetime as dt, timezone, timedelta
beijing_tz = timezone(timedelta(hours=8))
now_bj = dt.now(beijing_tz)
live_count = 0
done_count = 0
upcoming_count = 0
for p in preds:
    ko = p.get('kickoff', '23:59')
    try:
        h, m = map(int, ko.split(':'))
        ko_dt = now_bj.replace(hour=h, minute=m, second=0, microsecond=0)
        if ko_dt < now_bj - timedelta(hours=2):
            done_count += 1
        elif ko_dt < now_bj:
            live_count += 1
        else:
            upcoming_count += 1
    except:
        upcoming_count += 1

def pct(v): return f'{v*100:.1f}%'

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>午盘更新 · {date_str}</title>
<style>
:root{{--bg:#0b0c10;--card:#14161d;--border:#1e2030;--text:#c8ccd6;--dim:#656a78;--home:#4da6ff;--draw:#8b8fa3;--away:#f0a838;--green:#3fb950;--red:#f85149;--cyan:#00d4ff;--purple:#e879f9;}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:20px;line-height:1.5}}
.container{{max-width:1000px;margin:0 auto}}
.header{{text-align:center;padding:28px 0 20px;border-bottom:1px solid var(--border);margin-bottom:20px}}
.header h1{{font-size:1.3em}}.header .sub{{color:var(--dim);font-size:0.8em;margin-top:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7em;margin-left:6px;font-weight:600}}
.badge-v3{{background:#1a3a5c;color:var(--cyan)}}.badge-warn{{background:#3a2a0a;color:var(--away)}}
.summary{{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}}
.si{{flex:1;min-width:90px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;text-align:center}}
.si .n{{font-size:1.5em;font-weight:800}}.si .l{{font-size:0.65em;color:var(--dim);margin-top:4px}}
.si.warn .n{{color:var(--away)}}.si.info .n{{color:var(--cyan)}}
.diag-box{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px}}
.diag-box h3{{font-size:0.9em;color:var(--cyan);margin-bottom:10px}}
.diag-box p{{font-size:0.78em;color:var(--dim);line-height:1.7}}
table{{width:100%;border-collapse:collapse;font-size:0.78em}}
th{{text-align:left;padding:6px 10px;border-bottom:2px solid var(--border);color:var(--dim);font-size:0.7em}}
td{{padding:6px 10px;border-bottom:1px solid rgba(255,255,255,0.02)}}
.footer{{text-align:center;padding:28px;color:var(--dim);font-size:0.7em;border-top:1px solid var(--border);margin-top:28px}}
.league-line{{font-size:0.72em;color:var(--dim);padding:3px 0;display:flex;justify-content:space-between}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🌤️ 午盘更新<span class="badge badge-v3">v3.0</span></h1>
  <div class="sub">{date_str} · 赔率API双瘫痪 · 早盘→午盘零变动 · odds-api.io /odds配额耗尽</div>
</div>

<div class="summary">
  <div class="si info"><div class="n">{total}</div><div class="l">总场次</div></div>
  <div class="si warn"><div class="n">{cold}</div><div class="l">冷启动 🧊</div></div>
  <div class="si warn"><div class="n">0</div><div class="l">有赔率</div></div>
  <div class="si"><div class="n">{len(non_default)}</div><div class="l">已知ELO</div></div>
  <div class="si"><div class="n">0</div><div class="l">投注信号</div></div>
</div>

<div class="diag-box" style="border-color:rgba(248,81,73,0.4)">
  <h3>🚨 午盘诊断：API双瘫痪</h3>
  <p>
    <b style="color:var(--red)">赔率数据完全中断</b> — 早盘时odds-api.io v3 /odds端点尚有10场Kambi 1X2赔率，午盘重拉全部归零。月度免费配额已在49次查询中耗尽。<br>
    <b>早盘→午盘赔率移动：无</b> — 0场有赔率，无法对比变动。<br>
    <b>模型预测：无变化</b> — 50场均冷启动(联赛均值参数)，概率统一45.5/25.8/28.7。<br>
    <b>比赛状态</b> — 约{upcoming_count}场未开赛，部分欧战资格赛(UCL资格赛)即将或已在进行中。<br>
    <b>唯一已知球队: SK Brann</b> — 挪威超球队(ELO已知)对Apollon Limassol给出84.9%客胜概率，但该场无赔率无法检测edge。
  </p>
</div>

<div class="diag-box">
  <h3>📊 早盘 vs 午盘 对比</h3>
  <table>
  <tr><th>指标</th><th>早盘 (01:00)</th><th>午盘 (现在)</th><th>变动</th></tr>
  <tr><td>总场次</td><td>49</td><td>{total}</td><td>+1 (澳洲杯)</td></tr>
  <tr><td>有Kambi赔率</td><td style="color:var(--away)">10</td><td style="color:var(--red)">0</td><td style="color:var(--red)">-10 (配额耗尽)</td></tr>
  <tr><td>冷启动</td><td>49</td><td>{cold}</td><td>全部</td></tr>
  <tr><td>投注信号</td><td>0</td><td>0</td><td>—</td></tr>
  <tr><td>赔率移动>10%</td><td>—</td><td>N/A</td><td>0场有赔率</td></tr>
  </table>
</div>

<div class="diag-box">
  <h3>📡 API状态详情</h3>
  <table>
  <tr><td>the-odds-api.com v4</td><td style="color:var(--red)">配额耗尽 500/500</td><td>完全不可用</td></tr>
  <tr><td>odds-api.io v3 /events</td><td style="color:var(--green)">正常</td><td>300场/请求</td></tr>
  <tr><td>odds-api.io v3 /odds</td><td style="color:var(--red)">配额耗尽</td><td>50次查询→0赔率返回</td></tr>
  <tr><td>综合</td><td colspan="2" style="color:var(--red)">0场有赔率 · edge检测不可用 · 建议等待配额重置或更换数据源</td></tr>
  </table>
</div>

<div class="diag-box">
  <h3>⚽ 联赛分布 ({len(by_league)}个联赛 · {total}场)</h3>
'''
for lc in sorted(by_league.keys()):
    matches = by_league[lc]
    lcn = LEAGUE_CN.get(lc, lc)
    html += f'<div class="league-line"><span>{lcn}</span><span>{len(matches)}场 · 全部冷启动</span></div>'

html += f'''
</div>

<div class="footer">
  足球预测模型 v3.0 · 午盘更新 {date_str}<br>
  Dixon-Coles + 贝叶斯 + Kelly · 赔率源: 全部不可用<br>
  当前能力: 仅联赛均值概率(无区分度) · 无法edge检测 · 无投注信号
</div>
</div></body></html>'''

out_path = pathlib.Path(f'data/output/midday_analysis_{date_str}.html')
out_path.write_text(html, encoding='utf-8')
print(f'午盘报告已保存: {out_path}')
print(f'总场次: {total} · 冷启动: {cold} · 有赔率: 0 · 投注信号: 0')
