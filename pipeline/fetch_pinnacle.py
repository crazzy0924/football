"""拉取Pinnacle(平博)赔率 — 支持按开踢窗口过滤
用法:
  python pipeline/fetch_pinnacle.py                    # 全量
  python pipeline/fetch_pinnacle.py --window early     # ≤21:00 开踢
  python pipeline/fetch_pinnacle.py --window late      # >21:00 开踢
"""
import json, httpx, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

KEY = ''
env = Path(__file__).resolve().parent.parent / '.env'
if env.exists():
    for line in env.read_text(encoding='utf-8').splitlines():
        if line.startswith('ODDS_API_KEY='):
            KEY = line.split('=', 1)[1].strip(); break

LEAGUES = {
    'J1': 'soccer_japan_j_league',
    'J2': 'soccer_japan_j2_league',
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

# Parse window
window = None
for i, arg in enumerate(sys.argv):
    if arg == '--window' and i+1 < len(sys.argv):
        window = sys.argv[i+1]  # 'early' or 'late'

# Determine target date (default: today Beijing time)
# API returns UTC times, filter by Beijing date
beijing_tz = timezone(timedelta(hours=8))
target_date = datetime.now(beijing_tz).strftime('%Y-%m-%d')

if len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
    target_date = sys.argv[1]  # Allow explicit date override

print(f'Target date: {target_date}  |  Window: {window or "all"}  |  Beijing TZ')

for code, sport_key in LEAGUES.items():
    # J2 not covered by the-odds-api.com → skip fetch but note
    if code == 'J2':
        print(f'{code}: J2 not available on the-odds-api.com (skipped)')
        continue

    r = client.get(
        f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds',
        params={
            'apiKey': KEY, 'regions': 'eu',
            'markets': MARKETS, 'bookmakers': 'pinnacle',
            'oddsFormat': 'decimal', 'dateFormat': 'iso',
        }
    )
    desc = f'{code}: HTTP {r.status_code}'
    if r.status_code != 200:
        desc += ' ERR: ' + r.text[:150]
        print(desc)
        continue

    events = r.json()

    # Filter by target date (Beijing time)
    def is_target_date(event):
        ct = event.get('commence_time', '')
        if not ct: return False
        # API returns ISO format: "2026-08-09T17:00:00Z"
        utc_time = datetime.fromisoformat(ct.replace('Z', '+00:00'))
        bj_time = utc_time.astimezone(beijing_tz)
        return bj_time.strftime('%Y-%m-%d') == target_date

    league_today = [e for e in events if is_target_date(e)]
    desc += f' total={len(events)} today={len(league_today)}'

    # Apply window filter
    if window and league_today:
        def kickoff_hour(event):
            ct = event.get('commence_time', '')
            utc_time = datetime.fromisoformat(ct.replace('Z', '+00:00'))
            bj_time = utc_time.astimezone(beijing_tz)
            return bj_time.hour + bj_time.minute / 60.0

        before = []
        after = []
        for e in league_today:
            kh = kickoff_hour(e)
            if kh <= 21.0:
                before.append(e)
            else:
                after.append(e)

        if window == 'early':
            league_today = before
            desc += f' early(<=21:00)={len(league_today)}'
        elif window == 'late':
            league_today = after
            desc += f' late(>21:00)={len(league_today)}'
        else:
            desc += f' all={len(league_today)}'

    print(desc)

    for e in league_today:
        e['league_code'] = code
        today.append(e)
        home = e['home_team'][:28]; away = e['away_team'][:28]
        ct = e.get('commence_time', '')
        bj_str = ''
        if ct:
            utc_time = datetime.fromisoformat(ct.replace('Z', '+00:00'))
            bj_str = utc_time.astimezone(beijing_tz).strftime('%H:%M')
        for bm in e.get('bookmakers', []):
            mkts = [m['key'] for m in bm.get('markets', [])]
            extra = ''
            for m in bm['markets']:
                if m['key'] == 'spreads':
                    pts = [o.get('point') for o in m['outcomes']]
                    extra += f' AH:{pts}'
                elif m['key'] == 'totals':
                    pts = [o.get('point') for o in m['outcomes']]
                    extra += f' OU:{pts}'
            print(f'  {bj_str} {home} vs {away} | {mkts}{extra}')

# Determine output filename
if window:
    out = Path(f'data/pinnacle_{window}_{target_date}.json')
else:
    out = Path(f'data/pinnacle_odds_{target_date}.json')

out.write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nSaved {len(today)} matches -> {out}')
print(f'API used: {r.headers.get("x-requests-used", "?")}')
