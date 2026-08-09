"""Kambi驱动预测下注 — 胜平负+大小球 (Kambi真实赔率), 亚洲盘(仅体彩HHAD)"""
import json, sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.kambi_predictor import build_kambi_lookup
from pipeline.five_dim_predictor import compute_totals_probs

LEAGUE_CN = {'J1':'日职联','J2':'日乙','DED':'荷甲','BL2':'德乙','SWE':'瑞典超','FIN':'芬超','NOR':'挪超','PPL':'葡超','BSA':'巴甲'}

kambi = build_kambi_lookup('data/kambi_odds_20260809.json')

with open('data/output/predictions_2026-08-09.json', 'r', encoding='utf-8') as f:
    preds = json.load(f)
with open('data/today_matches_v3.json', 'r', encoding='utf-8') as f:
    matches = json.load(f)

en_to_cn = {}
for m in matches:
    en_to_cn[(m['home_team'], m['away_team'])] = (m.get('home_cn',''), m.get('away_cn',''))

# -- brute-force fuzzy matching for remaining --
def fuzzy_match(h_en, a_en):
    h_low = h_en.lower().replace(' ','').replace('-','').replace('.','')
    a_low = a_en.lower().replace(' ','').replace('-','').replace('.','')
    for (kh, ka), odds in kambi.items():
        kh_low = kh.lower().replace(' ','').replace('-','').replace('.','')
        ka_low = ka.lower().replace(' ','').replace('-','').replace('.','')
        if (h_low[:6] in kh_low or kh_low[:6] in h_low) and (a_low[:6] in ka_low or ka_low[:6] in a_low):
            return (kh, ka)
    return None

fixed = 0
for p in preds:
    h = p['home_team']; a = p['away_team']
    if (h, a) not in kambi:
        result = fuzzy_match(h, a)
        if result:
            kambi[(h, a)] = kambi[result]
            fixed += 1
            print(f'Fuzzy: {h} vs {a} -> {result[0]} vs {result[1]}')
        else:
            print(f'NO KAMBI: {h} vs {a}')

print(f'\nKambi matched: {sum(1 for p in preds if (p[\"home_team\"],p[\"away_team\"]) in kambi)}/{len(preds)} ({fixed} fuzzy)')

BANKROLL = 10000
KELLY_FRAC = 0.25
BETS = []

for p in preds:
    h_en = p['home_team']; a_en = p['away_team']
    lc = p['league_code']; cs = p['cold_start']
    cn = en_to_cn.get((h_en, a_en), (h_en, a_en))
    h_cn, a_cn = cn
    m = p['model']; sd = m.get('score_distribution', {})
    dc_h = m['home_win']; dc_d = m['draw']; dc_a = m['away_win']

    k1x2 = kambi.get((h_en, a_en), {}).get('1x2')
    ktot = kambi.get((h_en, a_en), {}).get('totals')
    dc_totals = compute_totals_probs(sd) if sd else None

    candidates = []

    # === 1X2: DC model vs Kambi Shin-devigged fair prob ===
    if k1x2:
        fair = k1x2['fair_probs']
        edges = {'home': dc_h - fair[0], 'draw': dc_d - fair[1], 'away': dc_a - fair[2]}
        best = max(edges, key=edges.get)
        kelly = max(0, edges[best])
        dirmap = {'home': '主胜', 'draw': '平局', 'away': '客胜'}
        if kelly > 0.005:
            odds_val = k1x2['raw'][best]
            candidates.append(('胜平负', dirmap[best], kelly, odds_val))

    # === Totals: DC model vs Kambi Shin-devigged fair ===
    if ktot and dc_totals:
        line = ktot['line']
        if abs(line - 2.5) < 0.1:
            dc_over = dc_totals['over_2_5']
        elif abs(line - 3.5) < 0.1:
            dc_over = dc_totals['over_3_5']
        else:
            dc_over = dc_totals.get('over_2_5', 0.5)

        over_edge = dc_over - ktot['fair_over']
        under_edge = (1 - dc_over) - ktot['fair_under']
        if over_edge > under_edge and over_edge > 0:
            kelly = over_edge
            direction = '大{:.1f}球'.format(line)
            odds_val = ktot['over_price']
        elif under_edge > 0:
            kelly = under_edge
            direction = '小{:.1f}球'.format(line)
            odds_val = ktot['under_price']
        else:
            kelly = 0; direction = ''; odds_val = None

        if kelly > 0.005:
            candidates.append(('大小球', direction, kelly, odds_val))

    # === Pick BEST single bet ===
    if candidates:
        best = max(candidates, key=lambda x: x[2])
        dim, direction, kelly, odds_val = best

        kf = min(kelly * KELLY_FRAC, 0.05)
        if cs: kf = min(kf, 0.02)
        stake = int(BANKROLL * kf)

        BETS.append({
            'home': h_cn, 'away': a_cn, 'league': LEAGUE_CN.get(lc, lc),
            'lc': lc, 'dim': dim, 'direction': direction,
            'kelly': kelly, 'odds': odds_val, 'stake': stake,
            'cold': cs,
        })

# Cap total exposure at 25%
total = sum(b['stake'] for b in BETS)
if total > 2500:
    scale = 2500 / total
    for b in BETS: b['stake'] = int(b['stake'] * scale)
total = sum(b['stake'] for b in BETS)

# Output
print()
print('=' * 95)
print('  JOYBOY  |  8月9日终盘下注单  |  Kambi(Unibet) 1X2+Totals  |  Shin去水  |  1/4 Kelly')
print('=' * 95)
print('  {:<22} {:<6} {:<8} {:<14} {:>6} {:>7} {:>7} {}'.format('比赛','联赛','维度','方向','赔率','凯利','投注','标记'))
print('-' * 95)

for b in BETS:
    odds_s = '{:.2f}'.format(b['odds']) if b['odds'] else '  --'
    cs_tag = 'COLD' if b['cold'] else ''
    print('  {:<22} {:<6} {:<8} {:<14} {:>6} {:>6.1%} {:>7} {}'.format(
        b['home'] + 'vs' + b['away'], b['league'], b['dim'], b['direction'],
        odds_s, b['kelly'], '$'+str(b['stake']), cs_tag))

print('-' * 95)
print('  {}场下注  总额 ${:,}  仓位 {:.1f}%  本金 $10,000'.format(len(BETS), total, total/BANKROLL*100))
print('  数据源: Kambi/Unibet (the-odds-api.com)  去水: Shin  模型: Dixon-Coles v3.0')

# Save
out = Path('data/output/kambi_bets_20260809.json')
out.write_text(json.dumps({'date':'2026-08-09','bets':BETS,'total':total,'source':'Kambi+Unibet+Shin'}, ensure_ascii=False, indent=2), encoding='utf-8')
print('\n[OK] ' + str(out))
