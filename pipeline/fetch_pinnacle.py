"""拉取Pinnacle(平博)赔率 — 1X2 + 亚洲盘 + 大小球 — 覆盖体彩当天比赛"""
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

MARKETS = 'h2h,spreads,totals'
client = httpx.Client(timeout=30)
today = []

for code, sport_key in LEAGUES.items():
    r = client.get(
        'https://api.the-odds-api.com/v4/sports/{}/odds'.format(sport_key),
        params={
            'apiKey': KEY, 'regions': 'eu',
            'markets': MARKETS, 'bookmakers': 'pinnacle',
            'oddsFormat': 'decimal', 'dateFormat': 'iso',
        }
    )
    desc = '{}: HTTP {}'.format(code, r.status_code)
    if r.status_code != 200:
        desc += ' ERR: ' + r.text[:150]
        print(desc)
        continue

    events = r.json()
    league_today = [e for e in events if e.get('commence_time', '')[:10] == '2026-08-09']
    desc += ' total={} today={}'.format(len(events), len(league_today))
    print(desc)

    for e in league_today:
        e['league_code'] = code
        today.append(e)
        home = e['home_team'][:28]; away = e['away_team'][:28]
        for bm in e.get('bookmakers', []):
            mkts = [m['key'] for m in bm.get('markets', [])]
            extra = ''
            for m in bm['markets']:
                if m['key'] == 'spreads':
                    pts = [o.get('point') for o in m['outcomes']]
                    extra += ' AH:{}'.format(pts)
                elif m['key'] == 'totals':
                    pts = [o.get('point') for o in m['outcomes']]
                    extra += ' OU:{}'.format(pts)
            print('  {} vs {} | {} {}'.format(home, away, mkts, extra))

out = Path('data/pinnacle_odds_20260809.json')
out.write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print('\nSaved {} matches -> {}'.format(len(today), out))
print('API used: {}'.format(r.headers.get('x-requests-used', '?')))
