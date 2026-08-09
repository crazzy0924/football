import json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.kambi_predictor import build_kambi_lookup
from pipeline.five_dim_predictor import compute_totals_probs

LEAGUE_CN = {
    'J1': '日职联', 'J2': '日乙', 'DED': '荷甲', 'BL2': '德乙',
    'SWE': '瑞典超', 'FIN': '芬超', 'NOR': '挪超', 'PPL': '葡超', 'BSA': '巴甲',
}

kambi = build_kambi_lookup('data/kambi_odds_20260809.json')

with open('data/output/predictions_2026-08-09.json', 'r', encoding='utf-8') as f:
    preds = json.load(f)
with open('data/today_matches_v3.json', 'r', encoding='utf-8') as f:
    matches = json.load(f)

en_to_cn = {}
for m in matches:
    en_to_cn[(m['home_team'], m['away_team'])] = (m.get('home_cn', ''), m.get('away_cn', ''))

# Fuzzy team name matching
def fuzzy(h, a):
    hl = h.lower().replace(' ', '').replace('-', '').replace('.', '')
    al = a.lower().replace(' ', '').replace('-', '').replace('.', '')
    for (kh, ka) in kambi:
        kl = kh.lower().replace(' ', '').replace('-', '').replace('.', '')
        ka_l = ka.lower().replace(' ', '').replace('-', '').replace('.', '')
        if (hl[:5] in kl or kl[:5] in hl) and (al[:5] in ka_l or ka_l[:5] in al):
            return (kh, ka)
    return None

for p in preds:
    h, a = p['home_team'], p['away_team']
    if (h, a) not in kambi:
        r = fuzzy(h, a)
        if r:
            kambi[(h, a)] = kambi[r]
            print('Fuzzy matched: {} vs {} -> {} vs {}'.format(h, a, r[0], r[1]))
        else:
            print('NO Kambi: {} vs {}'.format(h, a))

matched = sum(1 for p in preds if (p['home_team'], p['away_team']) in kambi)
print('Kambi coverage: {}/{}'.format(matched, len(preds)))

BANKROLL = 10000
KF = 0.25
BETS = []
DIRMAP = {'home': '主胜', 'draw': '平局', 'away': '客胜'}

for p in preds:
    h, a = p['home_team'], p['away_team']
    lc = p['league_code']
    cs = p['cold_start']
    cn = en_to_cn.get((h, a), (h, a))
    h_cn, a_cn = cn
    m = p['model']
    sd = m.get('score_distribution', {})
    dc_h, dc_d, dc_a = m['home_win'], m['draw'], m['away_win']

    k1x2 = kambi.get((h, a), {}).get('1x2')
    ktot = kambi.get((h, a), {}).get('totals')
    dc_totals = compute_totals_probs(sd) if sd else None

    candidates = []

    # 1X2: DC model vs Kambi fair prob
    if k1x2:
        fair = k1x2['fair_probs']
        edges = {'home': dc_h - fair[0], 'draw': dc_d - fair[1], 'away': dc_a - fair[2]}
        best = max(edges, key=edges.get)
        kelly = max(0, edges[best])
        if kelly > 0.005:
            candidates.append(('胜平负', DIRMAP[best], kelly, k1x2['raw'][best]))

    # Totals: DC vs Kambi fair
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
            candidates.append(('大小球', '大{:.1f}球'.format(line), over_edge, ktot['over_price']))
        elif under_edge > 0:
            candidates.append(('大小球', '小{:.1f}球'.format(line), under_edge, ktot['under_price']))

    if not candidates:
        continue

    best = max(candidates, key=lambda x: x[2])
    dim, direction, kelly, odds_val = best

    kf = min(kelly * KF, 0.05)
    if cs:
        kf = min(kf, 0.02)
    stake = int(BANKROLL * kf)

    BETS.append({
        'home': h_cn, 'away': a_cn, 'league': LEAGUE_CN.get(lc, lc),
        'dim': dim, 'direction': direction, 'kelly': kelly,
        'odds': odds_val, 'stake': stake, 'cold': cs,
    })

# Cap total exposure at 25%
total = sum(b['stake'] for b in BETS)
if total > 2500:
    scale = 2500.0 / total
    for b in BETS:
        b['stake'] = int(b['stake'] * scale)
total = sum(b['stake'] for b in BETS)

# Display
SEP = '-' * 90
print()
print(SEP)
print('  JOYBOY | 8/9 Kambi(Unibet) 1X2+Totals | Shin devig | 1/4 Kelly')
print(SEP)
print('  {:<3} {:<22} {:<6} {:<8} {:<14} {:>6} {:>7} {:>7}'.format(
    '', '比赛', '联赛', '维度', '方向', '赔率', '凯利', '投注'))
print(SEP)

for b in BETS:
    odds_s = '{:.2f}'.format(b['odds']) if b['odds'] else '  --  '
    tag = ' COLD' if b['cold'] else ''
    match_name = b['home'] + ' vs ' + b['away']
    print('  {:<3} {:<22} {:<6} {:<8} {:<14} {:>6} {:>6.0%} {:>7}'.format(
        tag, match_name, b['league'], b['dim'], b['direction'],
        odds_s, b['kelly'], '$' + str(b['stake'])))

print(SEP)
print('  {} bets  |  Total ${:,}  |  Exposure {:.1f}%  |  Bankroll $10,000'.format(
    len(BETS), total, total / BANKROLL * 100))
print('  Source: Kambi/Unibet via the-odds-api.com | Model: Dixon-Coles v3.0')

# Save
out = Path('data/output/kambi_bets_20260809.json')
out.write_text(json.dumps({
    'date': '2026-08-09', 'bets': BETS, 'total': total,
    'source': 'Kambi+Unibet+Shin',
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('\nSaved: ' + str(out))
