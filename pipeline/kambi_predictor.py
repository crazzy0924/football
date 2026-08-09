"""Kambi多维预测器 — 基于外围(Kambi/Unibet)赔率 + Dixon-Coles模型"""
from __future__ import annotations
import json, math
from pathlib import Path
from pipeline.five_dim_predictor import (
    compute_handicap_probs, compute_totals_probs, compute_correct_score_top
)

# === Shin去水 (1X2) ===
def shin_de_vig_1x2(h, d, a, max_iter=100):
    """Shin去水 → 真实概率 [home, draw, away]"""
    odds = [1/h, 1/d, 1/a]
    z0 = sum(odds)
    margin = z0 - 1.0
    if margin <= 0:
        return [o/z0 for o in odds], 0

    c = min(0.5, margin * 0.8)
    for _ in range(max_iter):
        denom = sum(math.sqrt(c + (1-c) * o**2) for o in odds)
        probs = [math.sqrt(c + (1-c) * o**2) / denom for o in odds]
        c_new = c * sum((1-p)**2 for p in probs) / (3 - sum(p**2 for p in probs))
        if abs(c_new - c) < 1e-6:
            break
        c = c_new
    return [round(p, 4) for p in probs], round(c, 6)

# === Shin去水 (二元, Over/Under) ===
def shin_de_vig_binary(price_over, price_under):
    """二元Shin去水 → [p_over, p_under]"""
    return shin_de_vig_multi([price_over, price_under])

def shin_de_vig_multi(prices):
    """n元Shin去水"""
    n = len(prices)
    odds = [1/p for p in prices]
    z0 = sum(odds)
    margin = z0 - 1.0
    if margin <= 0:
        return [round(o/z0, 4) for o in odds], 0

    c = min(0.5, margin * 0.8)
    for _ in range(100):
        denom = sum(math.sqrt(c + (1-c) * o**2) for o in odds)
        probs = [math.sqrt(c + (1-c) * o**2) / denom for o in odds]
        c_new = c * sum((1-p)**2 for p in probs) / (n - sum(p**2 for p in probs))
        if abs(c_new - c) < 1e-6:
            break
        c = c_new
    return [round(p, 4) for p in probs], round(c, 6)

# === Kambi队名→我们的英文名 ===
KAMBI_NAME_MAP = {
    # DED
    'Sparta Rotterdam': 'Sparta Rotterdam',
    'Feyenoord': 'Feyenoord',
    'FC Zwolle': 'Zwolle',
    'Ajax': 'Ajax',
    'Groningen': 'Groningen',
    'FC Utrecht': 'Utrecht',
    'Heerenveen': 'Heerenveen',
    'FC Twente Enschede': 'Twente',
    # BL2
    '1. FC Nurnberg': 'Nurnberg',
    'Dynamo Dresden': 'Dresden',
    'FC Energie Cottbus': 'Cottbus',
    'Hannover 96': 'Hannover',
    'FC St. Pauli': 'St. Pauli',
    'Greuther Furth': 'Furth',
    # SWE
    'Hammarby IF': 'Hammarby',
    'BK Hacken': 'Hacken',
    'Malmo FF': 'Malmo',
    'Degerfors IF': 'Degerfors',
    'Halmstads BK': 'Halmstads',
    'GAIS': 'GAIS',
    'IFK Goteborg': 'IFK Goteborg',
    'Kalmar FF': 'Kalmar',
    # FIN
    'KuPS Kuopio': 'KuPS',
    'TPS Turku': 'TPS',
    'FC Inter Turku': 'Inter Turku',
    'FC Lahti': 'Lahti',
    'Ilves Tampere': 'Ilves',
    'IFK Mariehamn': 'Mariehamn',
    'AC Oulu': 'AC Oulu',
    'HJK Helsinki': 'HJK',
    # NOR
    'Lillestrom': 'Lillestrom',
    'Rosenborg': 'Rosenborg',
    'HamKam': 'HamKam',
    'Aalesund': 'Aalesund',
    'Kristiansund BK': 'Kristiansund',
    'Molde': 'Molde',
    # PPL
    'FC Porto': 'Porto',
    'Alverca': 'Alverca',
    'Benfica': 'Benfica',
    'Academico de Viseu': 'Viseu',
    'Moreirense FC': 'Moreirense',
    'Braga': 'Braga',
    'Gil Vicente': 'Gil Vicente',
    'Rio Ave FC': 'Rio Ave',
    # BSA
    'Cruzeiro': 'Cruzeiro',
    'Mirassol': 'Mirassol',
    'Bahia': 'Bahia',
    'Vasco da Gama': 'Vasco',
    'Palmeiras': 'Palmeiras',
    'Internacional': 'Internacional',
    'Santos': 'Santos',
    'Atletico Paranaense': 'Athletico PR',
    'Bragantino-SP': 'Bragantino',
    'Corinthians': 'Corinthians',
    'Flamengo': 'Flamengo',
    'Vitoria': 'Vitoria',
}

def build_kambi_lookup(kambi_json_path: str) -> dict:
    """构建 Kambi 赔率查找表 key=(英文主队, 英文客队)"""
    with open(kambi_json_path, 'r', encoding='utf-8') as f:
        kambi = json.load(f)

    lookup = {}
    for e in kambi:
        h_raw = e['home_team']
        a_raw = e['away_team']
        h_en = KAMBI_NAME_MAP.get(h_raw, h_raw)
        a_en = KAMBI_NAME_MAP.get(a_raw, a_raw)

        odds = {'1x2': None, 'totals': None}
        for bm in e.get('bookmakers', []):
            if 'unibet' not in bm.get('key', '').lower():
                continue
            for mkt in bm['markets']:
                if mkt['key'] == 'h2h':
                    o = {x['name']: x['price'] for x in mkt['outcomes']}
                    raw_odds = {
                        'home': o.get(h_raw, 0),
                        'draw': o.get('Draw', 0),
                        'away': o.get(a_raw, 0),
                    }
                    if all(v > 0 for v in raw_odds.values()):
                        probs, margin = shin_de_vig_1x2(*raw_odds.values())
                        odds['1x2'] = {
                            'raw': raw_odds, 'fair_probs': probs, 'margin': margin,
                        }
                elif mkt['key'] == 'totals':
                    over_under = {}
                    for x in mkt['outcomes']:
                        pt = x.get('point')
                        if pt is not None:
                            key = f"over_{str(pt).replace('.','_')}"
                            over_under[x['name']] = {'point': pt, 'price': x['price']}

                    if 'Over' in over_under and 'Under' in over_under:
                        ov = over_under['Over']
                        un = over_under['Under']
                        probs, margin = shin_de_vig_binary(ov['price'], un['price'])
                        odds['totals'] = {
                            'line': ov['point'],
                            'over_price': ov['price'],
                            'under_price': un['price'],
                            'fair_over': probs[0],
                            'fair_under': probs[1],
                            'margin': margin,
                        }

        lookup[(h_en, a_en)] = odds

    return lookup

if __name__ == '__main__':
    lookup = build_kambi_lookup('data/kambi_odds_20260809.json')
    for (h, a), odds in sorted(lookup.items()):
        o1x2 = odds.get('1x2')
        otot = odds.get('totals')
        h2h_str = ''
        if o1x2:
            r = o1x2['raw']
            p = o1x2['fair_probs']
            h2h_str = f"Kambi {r['home']}/{r['draw']}/{r['away']} → fair {p[0]:.1%}/{p[1]:.1%}/{p[2]:.1%}"
        tot_str = ''
        if otot:
            tot_str = f"O/U{otot['line']} {otot['over_price']}/{otot['under_price']} → O{otot['fair_over']:.1%}/U{otot['fair_under']:.1%}"
        print(f'{h} vs {a}')
        if h2h_str: print(f'  {h2h_str}')
        if tot_str: print(f'  {tot_str}')
