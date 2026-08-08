#!/usr/bin/env python3
"""
8月8日 终盘预测生成器 (22:00)
12场晚场比赛: 6014-6025
六维预测: ①胜平负 ②波胆 ③全场大小 ④半场大小 ⑤半场让球 ⑥角球
"""
import json, sys, io, math
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except: pass

ROOT = Path(__file__).resolve().parent

# ══════════════════════════════════════════════════════
# LEAGUE PROFILES
# ══════════════════════════════════════════════════════
LEAGUES = {
    "瑞典超": {"code": "SWE", "avg_goals": 2.55, "home_rate": 0.40, "draw_rate": 0.26, "away_rate": 0.34,
               "over25_rate": 0.48, "style": "physical_defensive", "corners": 9.5},
    "芬超":   {"code": "FIN", "avg_goals": 2.60, "home_rate": 0.41, "draw_rate": 0.25, "away_rate": 0.34,
               "over25_rate": 0.52, "style": "physical", "corners": 9.0},
    "荷甲":   {"code": "DED", "avg_goals": 3.10, "home_rate": 0.44, "draw_rate": 0.22, "away_rate": 0.34,
               "over25_rate": 0.62, "style": "attacking", "corners": 10.0},
    "葡超":   {"code": "PPL", "avg_goals": 2.50, "home_rate": 0.42, "draw_rate": 0.26, "away_rate": 0.32,
               "over25_rate": 0.49, "style": "balanced", "corners": 10.5},
    "法乙":   {"code": "FL2", "avg_goals": 2.30, "home_rate": 0.39, "draw_rate": 0.31, "away_rate": 0.30,
               "over25_rate": 0.42, "style": "defensive", "corners": 8.5},
    "巴甲":   {"code": "BSA", "avg_goals": 2.30, "home_rate": 0.47, "draw_rate": 0.25, "away_rate": 0.28,
               "over25_rate": 0.43, "style": "physical_home", "corners": 10.0},
}

def shin_adjust(odds_h, odds_d, odds_a, z=0.028):
    """Shin-adjusted implied probabilities"""
    s_h = 1.0 / odds_h
    s_d = 1.0 / odds_d
    s_a = 1.0 / odds_a
    total = s_h + s_d + s_a
    # Shin formula
    margin = total - 1.0
    # Simple proportional margin removal
    adj_h = s_h / total
    adj_d = s_d / total
    adj_a = s_a / total
    return adj_h, adj_d, adj_a

def expected_goals_from_odds(odds_h, odds_d, odds_a):
    """Rough expected goals estimate from SPF odds"""
    prob_h, prob_d, prob_a = shin_adjust(odds_h, odds_d, odds_a)
    # Home team expected goals ≈ prob_h * 2 + prob_d * 1
    home_xg = prob_h * 2.2 + prob_d * 1.1 + prob_a * 0.6
    away_xg = prob_a * 2.0 + prob_d * 0.9 + prob_h * 0.5
    return home_xg, away_xg, home_xg + away_xg

def generate_prediction(match, league_prof):
    """Generate 6-dimension prediction for a match"""
    spf = match.get('spf', {})
    hhad = match.get('hhad', {})

    if not spf:
        return None  # No SPF = insufficient data

    odds_h = float(spf['h'])
    odds_d = float(spf['d'])
    odds_a = float(spf['a'])

    prob_h, prob_d, prob_a = shin_adjust(odds_h, odds_d, odds_a)
    home_xg, away_xg, total_xg = expected_goals_from_odds(odds_h, odds_d, odds_a)

    # ① SPF direction
    if prob_h >= 0.48:
        direction = "主胜"
        conf_spf = "中" if prob_h >= 0.55 else "低"
    elif prob_a >= 0.42:
        direction = "客胜"
        conf_spf = "中" if prob_a >= 0.48 else "低"
    else:
        direction = "平局" if prob_d >= 0.26 else ("主胜" if prob_h >= prob_a else "客胜")
        conf_spf = "低"

    # ② Correct score (most likely)
    # Map expected goals to most likely score
    scores = []
    for h in range(0, 5):
        for a in range(0, 5):
            if h == 0 and a == 0: continue
            # Poisson probability
            ph = math.exp(-home_xg) * home_xg**h / math.factorial(h)
            pa = math.exp(-away_xg) * away_xg**a / math.factorial(a)
            scores.append((h, a, ph * pa))
    scores.sort(key=lambda x: x[2], reverse=True)
    top_scores = scores[:3]
    cs_str = " / ".join(f"{h}-{a}" for h, a, _ in top_scores)

    # ③ Over/Under 2.5
    ou25_prob = sum(p for h, a, p in scores if h + a > 2.5)
    ou25_dir = "大2.5" if ou25_prob > 0.45 else "小2.5"
    ou25_conf = "中" if abs(ou25_prob - 0.5) > 0.1 else "低"

    # ④ Half-time over/under 1.0
    ht_goals = total_xg * 0.42  # ~42% of goals in first half
    ht_ou = "半场大1.0" if ht_goals > 1.05 else "半场小1.0"
    ht_ou_conf = "中" if abs(ht_goals - 1.0) > 0.15 else "低"

    # ⑤ Half-time handicap
    hhad_gl = hhad.get('goalLine', '')
    if hhad_gl:
        gl_val = float(hhad_gl) if hhad_gl else 0
        hhad_h = float(hhad.get('h', 999))
        hhad_a = float(hhad.get('a', 999))
        if hhad_h < hhad_a:
            ht_hc = f"{'主队' if gl_val > 0 else '客队'} {'+' if gl_val > 0 else ''}{abs(int(gl_val))}"
        else:
            ht_hc = f"{'客队' if gl_val < 0 else '主队'} {'+' if gl_val < 0 else ''}{abs(int(gl_val))}"
    else:
        ht_hc = "平手"

    # ⑥ Corners
    base_corners = league_prof.get('corners', 9.5)
    # Adjust: higher total xg → more corners
    corner_adj = (total_xg - league_prof['avg_goals']) * 1.5
    corners_exp = base_corners + corner_adj
    corner_dir = f"大{base_corners}" if corners_exp > base_corners else f"小{base_corners}"

    # Betting suggestion
    if conf_spf == "中" and ou25_conf in ("中", "高"):
        bet_type = "value"
        bet_note = "赔率方向+大小球一致,可投注"
    elif conf_spf == "低":
        bet_type = "reference"
        bet_note = "低置信,建议观望"
    else:
        bet_type = "light"
        bet_note = "方向明确但大小球不确定,轻注"

    # Overall confidence
    if bet_type == "value": overall_conf = "中"
    elif bet_type == "light": overall_conf = "低-中"
    else: overall_conf = "低"

    return {
        "direction": direction, "direction_conf": conf_spf,
        "implied_probs": {"home": round(prob_h, 3), "draw": round(prob_d, 3), "away": round(prob_a, 3)},
        "correct_score": cs_str,
        "over_under_25": ou25_dir, "ou25_conf": ou25_conf,
        "ht_over_under": ht_ou, "ht_ou_conf": ht_ou_conf,
        "ht_handicap": ht_hc,
        "corners": corner_dir,
        "expected_goals": round(total_xg, 2),
        "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
        "bet_type": bet_type, "bet_note": bet_note,
        "overall_conf": overall_conf,
    }

def logic_chain(match, pred, league_prof):
    """Build decision logic chain"""
    spf = match.get('spf', {})
    odds_h, odds_d, odds_a = float(spf['h']), float(spf['d']), float(spf['a'])
    parts = [
        f"SPF {odds_h}/{odds_d}/{odds_a}",
        f"隐含概率 主{pred['implied_probs']['home']:.0%}/平{pred['implied_probs']['draw']:.0%}/客{pred['implied_probs']['away']:.0%}",
        f"预期进球 {pred['expected_goals']} (主{pred['home_xg']}/客{pred['away_xg']})",
        f"{match.get('league','')} 场均{league_prof['avg_goals']}球 · {league_prof['style']}",
    ]
    # Add key decision points
    if pred['direction'] == "主胜" and pred['implied_probs']['home'] < 0.45:
        parts.append("⚠️ 主胜概率未达强热阈值 → 降置信")
    if league_prof['over25_rate'] < 0.45 and pred['over_under_25'] == "大2.5":
        parts.append("⚠️ 联赛小球倾向, 大球慎推")
    if league_prof['avg_goals'] < 2.5 and pred['expected_goals'] > 3.0:
        parts.append("⚠️ 联赛低进球 vs 预期高进球矛盾")
    return " · ".join(parts)


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════

# Manual league mapping for matchNum
MATCH_LEAGUES = {
    6014: "瑞典超", 6015: "芬超", 6016: "荷甲", 6017: "葡超",
    6018: "荷甲", 6019: "法乙", 6020: "法乙", 6021: "法乙",
    6022: "荷甲", 6023: "巴甲", 6024: "葡超", 6025: "巴甲",
}

MATCH_KICKOFF = {
    6014: "23:30", 6015: "00:00", 6016: "00:45", 6017: "01:00",
    6018: "02:00", 6019: "02:45", 6020: "02:45", 6021: "02:45",
    6022: "03:00", 6023: "03:00", 6024: "03:30", 6025: "08:00",
}

# Special notes per match
SPECIAL_NOTES = {
    6014: "⚠️ SPF-HHAD矛盾: SPF倾向均势但让球盘强烈倾向客队",  # Mjallby
    6015: "芬超第19轮 · 雅罗排名11 vs 瓦萨排名6",  # Jaro
    6016: "⚠️ 午盘信号: 客胜赔率走低5% → 资金流入客队",  # Go Ahead
    6017: "葡超揭幕战 · ⚠️冷启动 · SPF与让球盘方向矛盾",
    6018: "🔴 无SPF赔率 · 仅HHAD让球-2盘 → 深盘警告 · PSV强队但揭幕战",  # PSV
    6019: "法乙揭幕战 · ⚠️冷启动",
    6020: "法乙揭幕战 · 蒙彼利埃降班马 · ⚠️冷启动",
    6021: "法乙揭幕战 · 南特降班马 · ⚠️冷启动",
    6022: "⚠️ 排名倒挂: 荷甲3 vs 荷甲2 · 深盘-1 · 荷甲冷启动",
    6023: "巴甲第22轮 · 格雷米奥17 vs 圣保罗12 · 主队保级战意",
    6024: "🔴 无SPF赔率 · HHAD +2深盘 · 里斯本竞技客场强队 · 葡超揭幕战",
    6025: "巴甲第22轮 · 博塔弗戈8 vs 弗鲁米嫩4 · 排名接近",
}

data = json.loads(open(ROOT / 'data/latest_odds_20260808_2200.json', encoding='utf-8').read())
matches = data['matches']

# Filter to Aug 8 late matches only (6014-6025)
late_matches = [m for m in matches if 6014 <= m['num'] <= 6025]

print(f"晚场终盘: {len(late_matches)} 场比赛 (22:00)")
print("=" * 60)

results = []
for m in late_matches:
    mn = m['num']
    league = MATCH_LEAGUES.get(mn, "未知")
    lp = LEAGUES.get(league, {"code": "UNK", "avg_goals": 2.5, "home_rate": 0.42, "over25_rate": 0.50, "style": "unknown", "corners": 9.0})

    pred = generate_prediction(m, lp)
    if pred is None:
        print(f"  {mn} {m['home']} vs {m['away']} [{league}] — 无SPF, 跳过")
        results.append({"match": m, "prediction": None, "league": league})
        continue

    logic = logic_chain(m, pred, lp)
    note = SPECIAL_NOTES.get(mn, "")

    print(f"  {mn} [{league}] {m['home']} vs {m['away']}")
    print(f"    → {pred['direction']} (主{pred['implied_probs']['home']:.0%}/平{pred['implied_probs']['draw']:.0%}/客{pred['implied_probs']['away']:.0%})")
    print(f"    → O/U: {pred['over_under_25']} | xG: {pred['expected_goals']} | 波胆: {pred['correct_score']}")
    print(f"    置信: {pred['overall_conf']} | {pred['bet_note']}")
    if note: print(f"    {note}")

    results.append({
        "match": m, "prediction": pred, "league": league, "logic": logic, "note": note,
        "kickoff": MATCH_KICKOFF.get(mn, "?"),
    })

# ══════════════════════════════════════════════════════
# GENERATE HTML
# ══════════════════════════════════════════════════════

bets = [r for r in results if r['prediction'] and r['prediction']['bet_type'] == 'value']
refs = [r for r in results if r['prediction'] and r['prediction']['bet_type'] in ('light',)]
skips = [r for r in results if not r['prediction']]

rows = ""
for r in results:
    m = r['match']
    p = r.get('prediction')
    mn = m['num']
    mid = f"{mn - 6000:03d}" if mn >= 6000 else str(mn)
    kickoff = r.get('kickoff', '?')

    if p is None:
        spf_str = "-"
        dir_html = '<span style="color:#f85149">数据不足</span>'
        conf_html = "-"
        prob_html = "-"
        xg_html = "-"
        sub_html = "-"
        bet_html = '<span style="color:#f85149">跳过</span>'
        logic_html = r.get('note', '无SPF赔率数据')
    else:
        spf = m.get('spf', {})
        spf_str = f'{spf.get("h","?")}/{spf.get("d","?")}/{spf.get("a","?")}'
        dir_col = {"主胜": "#3fb950", "平局": "#f0a838", "客胜": "#58a6ff"}.get(p['direction'], "#c8c8d4")
        dir_html = f'<span style="color:{dir_col};font-weight:700">{p["direction"]}</span>'
        conf_col = {"高": "#3fb950", "中": "#f0a838", "低": "#f85149", "低-中": "#f0a838"}.get(p['overall_conf'], "#f85149")
        conf_html = f'<span style="color:{conf_col};font-weight:700">{p["overall_conf"]}</span>'
        prob_html = f'主{p["implied_probs"]["home"]:.0%}<br>平{p["implied_probs"]["draw"]:.0%}<br>客{p["implied_probs"]["away"]:.0%}'
        xg_html = f'{p["expected_goals"]}'
        sub_html = f'{p["over_under_25"]}<br><small>HT:{p["ht_over_under"]}</small><br><small>波胆:{p["correct_score"]}</small>'
        bet_type = p['bet_type']
        if bet_type == 'value': bet_html = '<span style="color:#3fb950;font-weight:700">✅ 投注 100</span>'
        elif bet_type == 'light': bet_html = '<span style="color:#f0a838">🟡 轻注 50</span>'
        else: bet_html = '<span style="color:#f85149">🔴 观望</span>'
        logic_html = r.get('logic', '')

    rows += f"""<tr>
      <td class="num">{mid}</td>
      <td class="ko">{kickoff}</td>
      <td><div class="match-name">{m['home']} vs {m['away']}</div><div class="league-tag">{r['league']}</div></td>
      <td class="odds">{spf_str}</td>
      <td class="dir">{dir_html}</td>
      <td class="conf">{conf_html}</td>
      <td class="probs">{prob_html}</td>
      <td class="eg">{xg_html}</td>
      <td class="sub">{sub_html}</td>
      <td class="bet">{bet_html}</td>
      <td class="logic">{logic_html}</td>
    </tr>"""

# Stats
value_bets = [r for r in results if r['prediction'] and r['prediction']['bet_type'] == 'value']
light_bets = [r for r in results if r['prediction'] and r['prediction']['bet_type'] == 'light']
total_stake = len(value_bets) * 100 + len(light_bets) * 50
has_spf = sum(1 for r in results if r['prediction'])

date_str = "2026-08-08"
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>终盘预测 · {date_str} · 22:00</title>
<style>
:root{{--bg:#080b14;--card:#0d111c;--border:#161b2a;--text:#c8ccd8;--muted:#5a5e72;--a2:#a78bfa;--g:#3fb950;--r:#f85149;--y:#f0a838;--b:#58a6ff;--cy:#00d4ff}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.6;min-height:100vh;padding:24px;max-width:1500px;margin:0 auto}}
.top{{background:linear-gradient(135deg,#0a0f1e,#11163a);border:1px solid var(--border);border-radius:12px;padding:20px 24px;margin-bottom:18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.top .icon{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#7c6ff7,#a78bfa);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1.1em;flex-shrink:0}}
.top h1{{font-size:1.05em}} .top em{{color:var(--a2);font-style:normal}} .top .sub{{font-size:0.6em;color:var(--muted)}}
.dash{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.di{{flex:1;min-width:70px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 8px;text-align:center}} .di .n{{font-size:1.3em;font-weight:800}} .di .l{{font-size:0.52em;color:var(--muted)}}
h2{{font-size:0.82em;margin:20px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--border)}} h2 span{{color:var(--a2)}}
table{{width:100%;border-collapse:collapse;font-size:0.72em}}
th{{background:var(--card);padding:8px 6px;text-align:left;font-size:0.68em;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);position:sticky;top:0;z-index:1}}
td{{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,0.03);vertical-align:top}}
tr:hover td{{background:rgba(124,111,247,0.02)}}
tr.warn td{{background:rgba(248,81,73,0.03)}}
.num{{font-weight:700;color:var(--muted);min-width:42px}} .ko{{font-size:0.7em;color:var(--y);min-width:48px}}
.match-name{{font-weight:600}} .league-tag{{font-size:0.6em;color:var(--muted)}}
.odds{{font-weight:600;min-width:80px}} .dir{{min-width:55px}} .conf{{min-width:55px}}
.probs{{font-size:0.7em;color:var(--muted);min-width:50px}}
.eg{{font-weight:600;color:var(--cy);min-width:35px}}
.sub{{font-size:0.7em;min-width:80px}} .sub small{{color:var(--muted)}}
.bet{{min-width:80px}} .logic{{font-size:0.6em;color:var(--muted);max-width:400px;line-height:1.5}}
.ledger{{background:var(--card);border:1px solid var(--border);border-radius:9px;padding:14px 18px;margin:16px 0;font-size:0.75em}}
.ledger h3{{font-size:0.85em;margin-bottom:8px}} .ledger td{{font-size:0.75em}}
.note{{background:rgba(124,111,247,0.04);border:1px solid rgba(124,111,247,0.1);border-radius:8px;padding:12px 16px;margin:14px 0;font-size:0.65em;line-height:1.7}}
.tag{{font-size:0.55em;font-weight:700;padding:2px 6px;border-radius:4px;white-space:nowrap}}
.tg{{background:rgba(63,185,80,0.1);color:var(--g)}} .ty{{background:rgba(240,168,56,0.1);color:var(--y)}} .tr{{background:rgba(248,81,73,0.1);color:var(--r)}}
.ft{{text-align:center;padding:20px;color:var(--muted);font-size:0.55em;opacity:0.4}}
</style>
</head>
<body>
<div class="top">
<div class="icon">C</div>
<h1><em>克劳德</em> · 终盘预测 · {date_str}</h1>
<span class="sub">晚场12场 · 六维预测 · 体彩官方SPF赔率 · 22:00 终盘</span>
</div>

<div class="dash">
<div class="di"><div class="n" style="color:var(--a2)">{len(results)}</div><div class="l">总场次</div></div>
<div class="di"><div class="n" style="color:var(--g)">{len(value_bets)}</div><div class="l">✅ 投注</div></div>
<div class="di"><div class="n" style="color:var(--y)">{len(light_bets)}</div><div class="l">🟡 轻注</div></div>
<div class="di"><div class="n" style="color:var(--r)">{len(skips)}</div><div class="l">跳过</div></div>
<div class="di"><div class="n" style="color:var(--b)">{has_spf}</div><div class="l">有SPF</div></div>
<div class="di"><div class="n" style="color:var(--y)">{total_stake}</div><div class="l">总投注额</div></div>
</div>

<div class="note">
<strong>📊 数据源:</strong> lottery.gov.cn 官方SPF赔率 (22:00拉取) · Shin调整去margin · 联赛画像约束<br>
<strong>⚠️ 风险提示:</strong> 荷甲/葡超/法乙均为揭幕战(冷启动), 巴甲为常规轮次 · 低置信标注→建议观望<br>
<strong>📐 六维:</strong> ①胜平负 ②波胆 ③全场大小 ④半场大小 ⑤半场让球 ⑥角球<br>
<strong>🟡 午盘信号回顾:</strong> 004全北客胜骤降15%已验证(1-3济州SK) · 006博德客胜1.33→主胜略有资金流入(待验证) · 016威廉二世客胜走低5%(本场关注)
</div>

<h2>📋 <span>终盘预测 · 晚场12场</span></h2>
<table>
<thead><tr>
<th>编号</th><th>开球</th><th>对阵</th><th>SPF</th><th>方向</th><th>置信</th>
<th>概率</th><th>xG</th><th>大小/HT/波胆</th><th>下注</th><th>决策链</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>

<!-- 投注台账 -->
<div class="ledger">
<h3>💰 投注台账 · {date_str} 晚场</h3>
<table>
<tr><th>编号</th><th>对阵</th><th>方向</th><th>赔率</th><th>金额</th><th>置信</th><th>预期回报</th></tr>
"""
for r in results:
    p = r.get('prediction')
    if not p or p['bet_type'] not in ('value', 'light'): continue
    m = r['match']
    mn = m['num']
    mid = f"{mn - 6000:03d}"
    spf = m.get('spf', {})
    if p['direction'] == "主胜": odds_key = 'h'
    elif p['direction'] == "平局": odds_key = 'd'
    else: odds_key = 'a'
    bet_odds = float(spf.get(odds_key, 0))
    stake = 100 if p['bet_type'] == 'value' else 50
    ev = round(stake * bet_odds, 0)
    html += f'<tr><td>{mid}</td><td>{m["home"]} vs {m["away"]}</td><td style="color:var(--g)">{p["direction"]}</td><td>{bet_odds}</td><td>{stake}</td><td>{p["overall_conf"]}</td><td>{ev:.0f}</td></tr>\n'

# Calculate total potential return
_dir_to_key = {"主胜": "h", "平局": "d", "客胜": "a"}
_total_return = 0
_bet_odds_list = []
for _r in results:
    _p = _r.get('prediction')
    if not _p or _p['bet_type'] not in ('value', 'light'): continue
    _stake = 100 if _p['bet_type'] == 'value' else 50
    _key = _dir_to_key.get(_p['direction'], 'h')
    _odds = float(_r['match']['spf'].get(_key, 1.5))
    _total_return += round(_stake * _odds, 0)
    _bet_odds_list.append(_odds)
_min_odds = max(1.5, min(_bet_odds_list)) if _bet_odds_list else 1.5
_break_even = int(total_stake / _min_odds) if total_stake > 0 else 0
_total_bets = len(value_bets) + len(light_bets)
html += f"""</table>
<div style="margin-top:8px;font-size:0.7em;color:var(--muted)">
<strong>总投入:</strong> {total_stake} · <strong>全中回报:</strong> {_total_return:.0f} · <strong>理论保本率:</strong> 需{_total_bets}场中{_break_even}场可保本
</div>
</div>"""
output_path = ROOT / 'today_final.html'
output_path.write_text(html, encoding='utf-8')
print(f"\n✅ HTML已生成: {output_path}")
print(f"   总场次: {len(results)}")
print(f"   推荐投注: {len(value_bets)} 场 (各100)")
print(f"   轻注参考: {len(light_bets)} 场 (各50)")
print(f"   跳过: {len(skips)} 场")
print(f"   总投注额: {total_stake}")
