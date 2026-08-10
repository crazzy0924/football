"""Fetch Kambi odds from odds-api.io v3 and convert to Pinnacle-compatible format"""
import httpx, json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import config

key = config.ODDS_API_IO_KEY
base = 'https://api.odds-api.io/v3'

# (event_id, home_kambi_name, away_kambi_name, league)
MATCHES = [
    (67126688, 'IK Sirius', 'IF Brommapojkarna', 'SWE'),
    (67126690, 'Vasteraas SK', 'Djurgardens IF', 'SWE'),
    (72530832, 'Santa Clara Azores', 'Nacional da Madeira', 'PPL'),
]
# Normalize to canonical English names matching predictions
NAME_FIX = {
    'Vasteraas SK': 'Västerås SK',
    'Djurgardens IF': 'Djurgårdens IF',
    'Santa Clara Azores': 'Santa Clara',
    'Nacional da Madeira': 'Nacional',
}

pinnacle_format = []

with httpx.Client(timeout=15, verify=False) as client:
    for eid, home_raw, away_raw, league in MATCHES:
        home_canon = NAME_FIX.get(home_raw, home_raw)
        away_canon = NAME_FIX.get(away_raw, away_raw)

        url = f'{base}/odds?apiKey={key}&eventId={eid}&bookmakers=Kambi'
        resp = client.get(url)
        if resp.status_code != 200:
            print(f'ERROR [{eid}]: {resp.status_code} {resp.text[:200]}')
            continue

        data = resp.json()
        kambi_markets = data.get('bookmakers', {}).get('Kambi', [])
        markets = []

        for mkt in kambi_markets:
            mkt_name = mkt['name']
            odds_list = mkt.get('odds', [])

            if mkt_name == 'ML' and odds_list:
                o = odds_list[0]
                markets.append({
                    'key': 'h2h',
                    'outcomes': [
                        {'name': home_canon, 'price': float(o['home'])},
                        {'name': 'Draw', 'price': float(o['draw'])},
                        {'name': away_canon, 'price': float(o['away'])},
                    ]
                })

            elif mkt_name == 'Spread' and odds_list:
                # Closest to even money = market-implied fair line
                best = min(odds_list, key=lambda o: abs(float(o['home']) - float(o['away'])))
                markets.append({
                    'key': 'spreads',
                    'outcomes': [
                        {'name': home_canon, 'point': float(best['hdp']), 'price': float(best['home'])},
                        {'name': away_canon, 'point': -float(best['hdp']), 'price': float(best['away'])},
                    ]
                })

            elif mkt_name == 'Totals' and odds_list:
                # Prefer 2.5 line, else closest to even money
                t25 = [o for o in odds_list if abs(o.get('hdp', 99) - 2.5) < 0.01]
                if t25:
                    o = t25[0]
                else:
                    o = min(odds_list, key=lambda o: abs(float(o['over']) - float(o['under'])))
                markets.append({
                    'key': 'totals',
                    'outcomes': [
                        {'name': 'Over', 'point': float(o['hdp']), 'price': float(o['over'])},
                        {'name': 'Under', 'point': float(o['hdp']), 'price': float(o['under'])},
                    ]
                })

        entry = {
            'home_team': home_canon,
            'away_team': away_canon,
            'bookmakers': [{'key': 'pinnacle', 'markets': markets}],
        }
        pinnacle_format.append(entry)
        print(f'[{eid}] {home_canon} vs {away_canon}: {len(markets)} markets')

date_str = '2026-08-10'
out_path = pathlib.Path(f'data/kambi_odds_{date_str}.json')
out_path.write_text(json.dumps(pinnacle_format, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'\nSaved {len(pinnacle_format)} matches to {out_path}')
