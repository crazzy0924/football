"""拉取Kambi(Unibet)外围赔率至 data/kambi_odds_20260809.json"""
import json, httpx
from pathlib import Path

KEY = ''
env = Path(__file__).resolve().parent.parent / '.env'
if env.exists():
    for line in env.read_text(encoding='utf-8').splitlines():
        if line.startswith('ODDS_API_KEY='):
            KEY = line.split('=', 1)[1].strip(); break

LEAGUES = {
    'J1': 'soccer_japan_j_league',
    'DED': 'soccer_netherlands_eredivisie',
    'BL2': 'soccer_germany_bundesliga2',
    'SWE': 'soccer_sweden_allsvenskan',
    'FIN': 'soccer_finland_veikkausliiga',
    'NOR': 'soccer_norway_eliteserien',
    'PPL': 'soccer_portugal_primeira_liga',
    'BSA': 'soccer_brazil_campeonato',
}

client = httpx.Client(timeout=30)
today = []

for code, sport in LEAGUES.items():
    r = client.get(f'https://api.the-odds-api.com/v4/sports/{sport}/odds', params={
        'apiKey': KEY, 'regions': 'eu',
        'markets': 'h2h,spreads,totals',
        'bookmakers': 'unibet', 'oddsFormat': 'decimal', 'dateFormat': 'iso',
    })
    print(f'{code}: {r.status_code} used={r.headers.get("x-requests-used")}')
    if r.status_code != 200:
        print(f'  ERROR: {r.text[:200]}')
        continue
    for e in r.json():
        if e.get('commence_time', '')[:10] == '2026-08-09':
            e['league_code'] = code
            today.append(e)
            home = e['home_team'][:28]
            away = e['away_team'][:28]
            # count markets
            for bm in e.get('bookmakers', []):
                if 'unibet' in bm.get('key', '').lower():
                    mkts = [m['key'] for m in bm.get('markets', [])]
                    print(f'  {home} vs {away} | {mkts}')

out = Path('data/kambi_odds_20260809.json')
out.write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nSaved {len(today)} matches → {out}')
