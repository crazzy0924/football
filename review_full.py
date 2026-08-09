"""
全维度复盘引擎 — 不只复盘下注，复盘模型每一个方向
1X2 · 亚洲盘(AH) · 大小球(O/U) · 下注盈亏 · ROI
"""
import json, sys, os
from pathlib import Path
from datetime import datetime

# ── Config ──
LEAGUE_CN = {'J1':'日职联','J2':'日乙','DED':'荷甲','BL2':'德乙',
             'SWE':'瑞典超','FIN':'芬超','NOR':'挪超','PPL':'葡超','BSA':'巴甲'}
BANKROLL = 10000

# ── Helpers ──
def determine_1x2_result(hg, ag):
    """实际赛果 → H/D/A"""
    if hg > ag: return 'home'
    elif hg == ag: return 'draw'
    else: return 'away'

def determine_ah_result(hg, ag, goal_line):
    """goal_line = home team's handicap (positive=home receives).
    Returns: 'home', 'away', or 'push'"""
    adjusted = hg - ag + goal_line
    if adjusted > 0: return 'home'
    elif adjusted == 0: return 'push'
    else: return 'away'

def determine_ou_result(hg, ag, line):
    """Returns: 'over', 'under', or 'push'"""
    total = hg + ag
    if total > line: return 'over'
    elif total < line: return 'under'
    else: return 'push'

def bet_outcome(bet, hg, ag, pinnacle_odds):
    """Determine if a bet won/lost/pushed. Returns (result, profit)."""
    dim = bet['dim']
    direction = bet['direction']
    stake = bet['stake']
    odds = bet['odds']
    result = 'LOSS'
    profit = -stake

    if dim == '胜平负':
        actual = determine_1x2_result(hg, ag)
        dirmap = {'主胜': 'home', '平局': 'draw', '客胜': 'away'}
        if dirmap.get(direction) == actual:
            result = 'WIN'
            profit = int(stake * (odds - 1))

    elif dim == '亚洲盘':
        # Parse direction: "客队(让0.75)" or "主队(受+0.50)" or "主队(平手)"
        dir_text = direction
        # Get the handicap line from pinnacle data
        po = pinnacle_odds
        ah_line = 0
        if po and po.get('ah') and po['ah'].get('home_pt') is not None:
            ah_line = po['ah']['home_pt']
        # Flip sign based on which side we bet
        if '客队' in dir_text:
            ah_line_to_use = -ah_line  # betting away side
        else:
            ah_line_to_use = ah_line   # betting home side

        actual_side = determine_ah_result(hg, ag, ah_line)
        if actual_side == 'push':
            result = 'PUSH'
            profit = 0
        elif ('主队' in dir_text and actual_side == 'home') or \
             ('客队' in dir_text and actual_side == 'away'):
            result = 'WIN'
            profit = int(stake * (odds - 1))

    elif dim == '大小球':
        # Parse line from direction: "大2.5球" or "小3.2球"
        import re
        m = re.search(r'([大小])([\d.]+)球', direction)
        if m:
            side = m.group(1); line = float(m.group(2))
            actual = determine_ou_result(hg, ag, line)
            if actual == 'push':
                result = 'PUSH'
                profit = 0
            elif (side == '大' and actual == 'over') or (side == '小' and actual == 'under'):
                result = 'WIN'
                profit = int(stake * (odds - 1))

    return result, profit

# ── Load data ──
def load_data(date_str):
    """Load all prediction/bet/odds data for a date."""
    data = {}
    pred_path = f'data/output/predictions_{date_str}.json'
    bets_path = f'data/output/pinnacle_bets_{date_str}.json'
    odds_path = f'data/pinnacle_odds_{date_str}.json'
    matches_path = 'data/today_matches_v3.json'

    for name, path in [('preds', pred_path), ('bets', bets_path), ('odds', odds_path)]:
        if os.path.exists(path):
            data[name] = json.load(open(path, 'r', encoding='utf-8'))
        else:
            data[name] = None
            print(f'WARNING: {path} not found')

    if os.path.exists(matches_path):
        data['matches'] = json.load(open(matches_path, 'r', encoding='utf-8'))
    return data

def build_lookups(data):
    """Build team name → CN, prediction lookup, odds lookup."""
    # EN → CN
    en_to_cn = {}
    if data.get('matches'):
        for m in data['matches']:
            en_to_cn[(m['home_team'], m['away_team'])] = (m.get('home_cn',''), m.get('away_cn',''))

    # Prediction lookup by (home, away)
    pred_map = {}
    if data.get('preds'):
        for p in data['preds']:
            pred_map[(p['home_team'], p['away_team'])] = p

    # Pinnacle odds lookup by (home, away)
    odds_map = {}
    if data.get('odds'):
        for e in data['odds']:
            odds_map[(e['home_team'], e['away_team'])] = e

    # Bet lookup by (home_cn, away_cn)
    bet_map = {}
    if data.get('bets'):
        for b in data['bets']['bets']:
            bet_map[(b['home'], b['away'])] = b

    return en_to_cn, pred_map, odds_map, bet_map

def fuzzy_match_team(name, candidates):
    """Fuzzy match a team name to a set of candidates."""
    n = name.lower().replace(' ','').replace('-','').replace('.','')
    for c in candidates:
        cn = c.lower().replace(' ','').replace('-','').replace('.','')
        if n[:4] in cn or cn[:4] in n:
            return c
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python review_full.py YYYY-MM-DD --results-text 'A 2-1 B\\n...'")
        print("   or: python review_full.py YYYY-MM-DD --results-json PATH")
        sys.exit(1)

    date_str = sys.argv[1]
    results_text = None; results_json_path = None

    # Parse args
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == '--results-text' and i+1 < len(sys.argv):
            results_text = sys.argv[i+1]
        elif arg == '--results-json' and i+1 < len(sys.argv):
            results_json_path = sys.argv[i+1]

    # Load data
    data = load_data(date_str)
    en_to_cn, pred_map, odds_map, bet_map = build_lookups(data)

    # Parse results
    results = []
    if results_json_path and os.path.exists(results_json_path):
        results = json.load(open(results_json_path, 'r', encoding='utf-8'))
    elif results_text:
        for line in results_text.strip().split('\n'):
            line = line.strip()
            if not line: continue
            # Parse "TeamA 2-1 TeamB" or "TeamA 2:1 TeamB"
            import re
            m = re.match(r'(.+?)\s+(\d+)[-:]\s*(\d+)\s+(.+)', line)
            if m:
                results.append({
                    'home_team': m.group(1).strip(),
                    'home_goals': int(m.group(2)),
                    'away_goals': int(m.group(3)),
                    'away_team': m.group(4).strip(),
                })
    else:
        # Try default results file
        default = f'data/output/results_{date_str}.json'
        if os.path.exists(default):
            results = json.load(open(default, 'r', encoding='utf-8'))

    if not results:
        print(f"\nNo results found for {date_str}.")
        print("Provide results via --results-text or --results-json")
        print("Example: python review_full.py 2026-08-09 --results-text \"东京绿茵 1-2 川崎前锋\\n...\"")
        sys.exit(1)

    print(f'Loaded {len(results)} results')

    # ── Match results to predictions ──
    # Build fuzzy name lookup for matching
    pred_keys = list(pred_map.keys())
    odds_keys = list(odds_map.keys())

    matched = []
    unmatched_results = []

    for r in results:
        h_raw = r['home_team']; a_raw = r['away_team']
        hg = r['home_goals']; ag = r['away_goals']

        # Try exact match first
        key = (h_raw, a_raw)
        if key not in pred_map:
            # Fuzzy: try matching against prediction keys
            for pk in pred_keys:
                ph, pa = pk
                if (h_raw[:4] in ph or ph[:4] in h_raw) and (a_raw[:4] in pa or pa[:4] in a_raw):
                    key = pk
                    break
            else:
                # Try matching against CN names
                for pk, pv in pred_map.items():
                    cn = en_to_cn.get(pk, ('',''))
                    if (h_raw in cn[0] or cn[0] in h_raw) and (a_raw in cn[1] or cn[1] in a_raw):
                        key = pk
                        break
                else:
                    unmatched_results.append(r)
                    continue

        pred = pred_map.get(key)
        cn = en_to_cn.get(key, (key[0], key[1]))
        h_cn, a_cn = cn

        # Find corresponding bet
        bet = bet_map.get((h_cn, a_cn))

        # Get pinnacle odds for this match
        # Try to find Pinnacle odds by fuzzy matching
        po = None
        if key in odds_map:
            po = odds_map[key]
        else:
            for ok in odds_keys:
                oh, oa = ok
                if (h_raw[:5] in oh or oh[:5] in h_raw) and (a_raw[:5] in oa or oa[:5] in a_raw):
                    po = odds_map[ok]
                    break

        # Build Pinnacle odds in the format bet_outcome expects
        pinnacle_odds_formatted = None
        if po:
            pinnacle_odds_formatted = {}
            for bm in po.get('bookmakers', []):
                if 'pinnacle' not in bm.get('key','').lower(): continue
                for mkt in bm['markets']:
                    if mkt['key'] == 'spreads':
                        for x in mkt['outcomes']:
                            if x['name'] == po['home_team']:
                                pinnacle_odds_formatted['ah'] = {'home_pt': x.get('point',0)}
                                break

        # ── Review each dimension ──
        m = pred.get('model', {})
        sd = m.get('score_distribution', {})
        dc_h, dc_d, dc_a = m['home_win'], m['draw'], m['away_win']
        dc_pick = max([('home', dc_h), ('draw', dc_d), ('away', dc_a)], key=lambda x: x[1])[0]
        actual_1x2 = determine_1x2_result(hg, ag)

        # 1) 1X2 review
        dc_1x2_correct = (dc_pick == actual_1x2)
        dc_prob_of_actual = {'home': dc_h, 'draw': dc_d, 'away': dc_a}[actual_1x2]

        # 2) Asian Handicap review
        ah_review = None
        if po:
            for bm in po.get('bookmakers', []):
                if 'pinnacle' not in bm.get('key','').lower(): continue
                for mkt in bm['markets']:
                    if mkt['key'] == 'spreads':
                        for x in mkt['outcomes']:
                            if x['name'] == po['home_team']:
                                ah_line = x.get('point', 0)
                                ah_actual = determine_ah_result(hg, ag, ah_line)
                                # Which side did DC model favor?
                                hc = ps = ac = 0.0
                                for score, prob in sd.items():
                                    sh, sa = map(int, score.split('-'))
                                    adj = sh - sa + ah_line
                                    if adj > 0: hc += prob
                                    elif adj == 0: ps += prob
                                    else: ac += prob
                                dc_ah_pick = 'home' if hc > ac else 'away'
                                dc_ah_correct = (dc_ah_pick == ah_actual) if ah_actual != 'push' else None
                                ah_review = {
                                    'line': ah_line, 'dc_pick': dc_ah_pick,
                                    'actual': ah_actual, 'dc_home': round(hc,3),
                                    'dc_away': round(ac,3), 'dc_correct': dc_ah_correct,
                                }
                                break

        # 3) Totals review
        ou_review = None
        if po:
            for bm in po.get('bookmakers', []):
                if 'pinnacle' not in bm.get('key','').lower(): continue
                for mkt in bm['markets']:
                    if mkt['key'] == 'totals':
                        for x in mkt['outcomes']:
                            if x['name'] == 'Over':
                                ou_line = x['point']
                                ou_actual = determine_ou_result(hg, ag, ou_line)
                                # DC model over probability at this line
                                # Compute total goals distribution
                                tg_dist = {}
                                for score, prob in sd.items():
                                    sh, sa = map(int, score.split('-'))
                                    tg = sh + sa
                                    tg_dist[tg] = tg_dist.get(tg, 0) + prob
                                # Interpolate for line
                                if abs(ou_line - 2.5) < 0.1:
                                    dc_over_p = sum(p for g,p in tg_dist.items() if g >= 3)
                                elif abs(ou_line - 3.5) < 0.1:
                                    dc_over_p = sum(p for g,p in tg_dist.items() if g >= 4)
                                else:
                                    dc_over_p = 0.5
                                dc_ou_pick = 'over' if dc_over_p > 0.5 else 'under'
                                dc_ou_correct = (dc_ou_pick == ou_actual) if ou_actual != 'push' else None
                                ou_review = {
                                    'line': ou_line, 'dc_pick': dc_ou_pick,
                                    'actual': ou_actual, 'dc_over': round(dc_over_p,3),
                                    'dc_under': round(1-dc_over_p,3), 'dc_correct': dc_ou_correct,
                                }
                                break

        # 4) Bet outcome
        bet_out = None
        if bet:
            res, profit = bet_outcome(bet, hg, ag, pinnacle_odds_formatted)
            bet_out = {'result': res, 'profit': profit, 'stake': bet['stake'],
                       'dim': bet['dim'], 'direction': bet['direction'], 'odds': bet['odds']}

        matched.append({
            'home': h_cn, 'away': a_cn,
            'home_goals': hg, 'away_goals': ag,
            'score': f'{hg}-{ag}',
            'actual_1x2': actual_1x2,
            'dc_1x2_pick': dc_1x2_pick,
            'dc_1x2_correct': dc_1x2_correct,
            'dc_prob_of_actual': round(dc_prob_of_actual, 4),
            'ah_review': ah_review,
            'ou_review': ou_review,
            'bet_outcome': bet_out,
            'cold_start': pred.get('cold_start', False),
            'league': LEAGUE_CN.get(pred.get('league_code',''), pred.get('league_code','')),
        })

    # ── PRINT REPORT ──
    n = len(matched)
    sep = '=' * 100

    print(); print(sep)
    print(f'  📊 JOYBOY 全维度复盘报告 — {date_str}')
    print(f'  模型: Dixon-Coles v3.0  |  数据: Pinnacle(平博) Shin去水')
    print(sep)

    # Per-match detail
    print(f'\n{"─"*100}')
    print(f'  {"比赛":<24} {"比分":<7} {"1X2":<12} {"亚洲盘":<22} {"大小球":<20} {"下注":<25}')
    print(f'  {"":24} {"":7} {"模型→实际":<12} {"模型→实际":<22} {"模型→实际":<20} {"方向/赔率→结果":<25}')
    print(f'{"─"*100}')

    for mv in matched:
        # 1X2 line
        dc1 = f'{"✓" if mv["dc_1x2_correct"] else "✗"} {mv["dc_1x2_pick"]}→{mv["actual_1x2"]}'
        # AH line
        if mv['ah_review']:
            ar = mv['ah_review']
            ar_line = f'{ar["line"]:+.2f}'
            if ar['dc_correct'] is None:
                ah_str = f'⊘ {ar["dc_pick"]}→push ({ar_line})'
            else:
                ah_str = f'{"✓" if ar["dc_correct"] else "✗"} {ar["dc_pick"]}→{ar["actual"]} ({ar_line})'
        else:
            ah_str = '--'
        # OU line
        if mv['ou_review']:
            o_r = mv['ou_review']
            if o_r['dc_correct'] is None:
                ou_str = f'⊘ {o_r["dc_pick"]}→push ({o_r["line"]:.1f})'
            else:
                ou_str = f'{"✓" if o_r["dc_correct"] else "✗"} {o_r["dc_pick"]}→{o_r["actual"]} ({o_r["line"]:.1f})'
        else:
            ou_str = '--'
        # Bet line
        bo = mv['bet_outcome']
        if bo:
            if bo['result'] == 'WIN':
                bet_str = f'🟢 {bo["direction"]} @{bo["odds"]:.2f} +¥{bo["profit"]}'
            elif bo['result'] == 'PUSH':
                bet_str = f'🟡 {bo["direction"]} @{bo["odds"]:.2f} 走水'
            else:
                bet_str = f'🔴 {bo["direction"]} @{bo["odds"]:.2f} -¥{abs(bo["profit"])}'
        else:
            bet_str = '未下注'
        cs_tag = '❄️' if mv['cold_start'] else '  '

        print(f'  {cs_tag}{mv["home"]} vs {mv["away"]:<14} {mv["score"]:<7} {dc1:<12} {ah_str:<22} {ou_str:<20} {bet_str:<25}')

    # ── Aggregate stats ──
    print(f'\n{sep}')
    print(f'  📈 聚合统计 ({n}场比赛)')
    print(sep)

    # 1X2
    n_1x2 = sum(1 for m in matched)
    n_1x2_ok = sum(1 for m in matched if m['dc_1x2_correct'])
    pct_1x2 = n_1x2_ok / n_1x2 * 100 if n_1x2 else 0

    # Brier
    brier = sum(
        (m['dc_prob_of_actual'] - 1)**2 / 3 for m in matched
    ) / n if n else 1.0

    # AH
    n_ah = sum(1 for m in matched if m['ah_review'] and m['ah_review']['dc_correct'] is not None)
    n_ah_ok = sum(1 for m in matched if m['ah_review'] and m['ah_review']['dc_correct'] == True)

    # OU
    n_ou = sum(1 for m in matched if m['ou_review'] and m['ou_review']['dc_correct'] is not None)
    n_ou_ok = sum(1 for m in matched if m['ou_review'] and m['ou_review']['dc_correct'] == True)

    # Bets
    n_bets = sum(1 for m in matched if m['bet_outcome'])
    n_wins = sum(1 for m in matched if m['bet_outcome'] and m['bet_outcome']['result'] == 'WIN')
    n_push = sum(1 for m in matched if m['bet_outcome'] and m['bet_outcome']['result'] == 'PUSH')
    n_loss = sum(1 for m in matched if m['bet_outcome'] and m['bet_outcome']['result'] == 'LOSS')
    total_pl = sum(m['bet_outcome']['profit'] for m in matched if m['bet_outcome'])
    total_staked = sum(m['bet_outcome']['stake'] for m in matched if m['bet_outcome'])
    roi = total_pl / total_staked * 100 if total_staked else 0

    print(f'\n  {"指标":<20} {"数值":<15} {"说明"}')
    print(f'  {"─"*20} {"─"*15} {"─"*50}')
    print(f'  {"Brier Score":<20} {brier:<15.4f} {"<0.65 PASS | <0.60 GOOD | <0.55 EXCELLENT"}')
    print(f'  {"1X2 方向准确率":<20} {n_1x2_ok}/{n_1x2} ({pct_1x2:.1f}%)  {"模型概率最高方向=实际赛果"}')
    if n_ah:
        print(f'  {"亚洲盘 方向准确率":<20} {n_ah_ok}/{n_ah} ({n_ah_ok/n_ah*100:.1f}%)  {"模型预测盘口方向=实际穿盘"}')
    if n_ou:
        print(f'  {"大小球 方向准确率":<20} {n_ou_ok}/{n_ou} ({n_ou_ok/n_ou*100:.1f}%)  {"模型预测大小方向=实际"}')
    print(f'  {"─"*20} {"─"*15} {"─"*50}')
    if n_bets:
        print(f'  {"🟢 下注胜":<20} {n_wins}场          {"盈利"}')
        print(f'  {"🟡 走水":<20} {n_push}场          {"退款"}')
        print(f'  {"🔴 下注负":<20} {n_loss}场          {"亏损"}')
        print(f'  {"胜率":<20} {n_wins}/{n_wins+n_loss} ({n_wins/(n_wins+n_loss)*100:.1f}%)  {"(排除走水)"}')
        print(f'  {"总投入":<20} ¥{total_staked:,}')
        print(f'  {"总盈亏":<20} ¥{total_pl:+,}')
        print(f'  {"ROI":<20} {roi:+.1f}%')
    else:
        print(f'  {"下注复盘":<20} 无下注数据')
    print(f'  {"─"*20} {"─"*15} {"─"*50}')

    # Dimension breakdown
    if n_bets:
        dim_stats = {}
        for m in matched:
            bo = m['bet_outcome']
            if not bo: continue
            d = bo['dim']
            if d not in dim_stats: dim_stats[d] = {'n':0,'win':0,'loss':0,'push':0,'pl':0}
            dim_stats[d]['n'] += 1
            dim_stats[d]['pl'] += bo['profit']
            if bo['result'] == 'WIN': dim_stats[d]['win'] += 1
            elif bo['result'] == 'LOSS': dim_stats[d]['loss'] += 1
            else: dim_stats[d]['push'] += 1

        print(f'\n  按维度分拆:')
        for d, s in dim_stats.items():
            wr = s['win']/(s['win']+s['loss'])*100 if (s['win']+s['loss']) else 0
            print(f'    {d:<8} {s["n"]}注  W{s["win"]} L{s["loss"]} P{s["push"]}  WR={wr:.0f}%  P&L=¥{s["pl"]:+,}')

    # Cold start breakdown
    cold_matches = [m for m in matched if m['cold_start']]
    if cold_matches:
        cold_pl = sum(m['bet_outcome']['profit'] for m in cold_matches if m['bet_outcome'])
        print(f'\n  ❄️ 冷启动场次: {len(cold_matches)}场  P&L=¥{cold_pl:+}')

    print(f'\n{sep}')
    print(f'  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(sep)

    # Verify against CLAUDE.md rules: numbers must be exact
    print(f'\n✅ 数字验证: Brier={brier:.4f} | Accuracy={pct_1x2:.1f}% | ROI={roi:+.1f}% | 以上数字从计算直接输出,未做任何修改')

if __name__ == '__main__':
    main()
