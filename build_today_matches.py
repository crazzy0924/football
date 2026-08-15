"""Build today.json from odds-api.io events + Kambi odds"""
import httpx, json, sys, io, pathlib
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import config

key = config.ODDS_API_IO_KEY
beijing_tz = timezone(timedelta(hours=8))
target_date = sys.argv[1] if len(sys.argv) > 1 else '2026-08-12'

# Map odds-api.io league slugs → internal league codes
# Codes match ELO state (data/state/elo_ratings.json) where available
LEAGUE_SLUG_MAP = {
    # === Big 5 Europe ===
    'england-premier-league': 'PL',
    'spain-la-liga': 'PD',
    'germany-bundesliga': 'BL1',
    'italy-serie-a': 'SA',
    'france-ligue-1': 'FL1',
    # === 2nd tier Big 5 ===
    'england-championship': 'ELC',
    'germany-bundesliga-2': 'BL2',
    'spain-la-liga-2': 'PD2',
    'france-ligue-2': 'FL2',
    'italy-serie-b': 'SB',
    # === Other European leagues (tracked in ELO) ===
    'netherlands-eredivisie': 'DED',
    'portugal-liga-portugal': 'PPL',
    'belgium-first-division-a': 'BPL',
    'turkiye-super-lig': 'TUR',
    'greece-super-league': 'GRE',
    'norway-eliteserien': 'NO1',
    'sweden-allsvenskan': 'SWE',
    'finland-veikkausliiga': 'FIN',
    'scotland-premiership': 'SPL',
    # === Americas (tracked in ELO) ===
    'brazil-brasileiro-a': 'BSA',
    'brazil-brasileiro-b': 'BS1',
    'argentina-primera-division': 'ARG',
    'usa-mls': 'MLS',
    # === Asia (tracked in ELO) ===
    'japan-j1-league': 'J1',
    'japan-j2-league': 'J2',
    # === UEFA club competitions (NEW - Aug 2026 qualifying) ===
    'international-clubs-uefa-champions-league-qualification': 'UCL',
    'international-clubs-uefa-europa-league-qualification': 'UEL',
    'international-clubs-uefa-conference-league-qualification': 'UEC',
    # === CONMEBOL club competitions (NEW) ===
    'international-clubs-conmebol-libertadores-knockout-stage': 'CLB',
    'international-clubs-conmebol-sudamericana-knockout-stage': 'CSD',
    # === Other Americas (NEW) ===
    'international-clubs-leagues-cup-group-stage': 'LGC',
    'colombia-torneo-dimayor-clausura': 'COL',
    'colombia-liga-dimayor-finalizacion': 'COL',
    'argentina-primera-lpf-clausura': 'ARG',
    # === Other notable leagues (NEW - Aug 2026) ===
    'south-africa-premiership': 'RSA',
    'czechia-czech-cup': 'CZE',
    'denmark-dbu-pokalen': 'DEN',
    'sweden-superettan': 'SW2',
    'australia-australia-cup-knockout-stage': 'AUS',
    'canada-canadian-championship': 'CAN',
    'chile-liga-de-ascenso': 'CHI',
    'romania-cupa-romaniei-knockout-stage': 'ROM',
    'bulgaria-vtora-liga': 'BUL',
    # === Lower tiers (tracked) ===
    'england-league-1': 'EL1',
    'england-league-2': 'EL2',
    'england-efl-cup': 'EFL',
    'germany-3-liga': 'BL3',
    'russia-premier-league': 'RPL',
    'korea-k-league-1': 'KLEAGUE',
    'china-super-league': 'CSL',
    'mexico-liga-mx': 'LMX',
    'austria-bundesliga': 'AUT',
    'denmark-superligaen': 'DEN',
    'poland-ekstraklasa': 'POL',
    'serbia-super-liga': 'SRB',
    'slovenia-prvaliga': 'SVN',
    'croatia-hnl': 'HRV',
    'slovakia-superliga': 'SVK',
    'hungary-nb-i': 'HUN',
    # === Amateur/youth/reserve - skip (mapped to None below) ===
}

# Canonical team name fixes
NAME_FIX = {
    'Vasteraas SK': 'Västerås SK',
    'Djurgardens IF': 'Djurgårdens IF',
    'Santa Clara Azores': 'Santa Clara',
    'Nacional da Madeira': 'Nacional',
}

# Step 1: Get events
print(f'=== Fetching events for {target_date} ===')
all_today = []
with httpx.Client(timeout=15) as client:
    resp = client.get(f'https://api.odds-api.io/v3/events?apiKey={key}&sport=football&limit=300')
    if resp.status_code != 200:
        print(f'ERROR: {resp.status_code}'); sys.exit(1)
    for e in resp.json():
        ct = e.get('date', '')
        if not ct: continue
        utc_time = datetime.fromisoformat(ct.replace('Z', '+00:00'))
        bj_time = utc_time.astimezone(beijing_tz)
        if bj_time.strftime('%Y-%m-%d') == target_date:
            slug = e['league']['slug']
            lc = LEAGUE_SLUG_MAP.get(slug)
            if lc:
                all_today.append({
                    'id': e['id'], 'home': e['home'], 'away': e['away'],
                    'league_code': lc, 'league_name': e['league']['name'],
                    'kickoff_bj': bj_time.strftime('%H:%M'),
                    'bj_hour': bj_time.hour + bj_time.minute/60.0,
                })

print(f'Mapped matches: {len(all_today)}')
leagues = {}
for m in all_today:
    lc = m['league_code']
    leagues[lc] = leagues.get(lc, 0) + 1
print(f'Leagues: {leagues}')

# Step 2: Build match list for today.json
# For each match, try to get Kambi odds
KAMBI_EVENT_IDS = [m['id'] for m in all_today]
print(f'\nFetching Kambi odds for {len(KAMBI_EVENT_IDS)} matches...')

kambi_data = {}
with httpx.Client(timeout=15) as client:
    for i, eid in enumerate(KAMBI_EVENT_IDS):
        url = f'https://api.odds-api.io/v3/odds?apiKey={key}&eventId={eid}&bookmakers=Kambi'
        resp = client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            kambi_markets = data.get('bookmakers', {}).get('Kambi', [])
            if kambi_markets:
                h2h_odds = None
                for mkt in kambi_markets:
                    if mkt['name'] == 'ML' and mkt.get('odds'):
                        o = mkt['odds'][0]
                        h2h_odds = {'home': float(o['home']), 'draw': float(o['draw']), 'away': float(o['away'])}
                        break
                if h2h_odds:
                    kambi_data[eid] = h2h_odds
        if (i+1) % 20 == 0:
            print(f'  {i+1}/{len(KAMBI_EVENT_IDS)}...')

print(f'Got Kambi odds for {len(kambi_data)}/{len(KAMBI_EVENT_IDS)} matches')

# Step 3: Build today.json
today = []
for m in all_today:
    home = NAME_FIX.get(m['home'], m['home'])
    away = NAME_FIX.get(m['away'], m['away'])
    entry = {
        'home_team': home,
        'away_team': away,
        'league_code': m['league_code'],
        'kickoff': m['kickoff_bj'],
    }
    if m['id'] in kambi_data:
        entry['odds'] = kambi_data[m['id']]
    today.append(entry)

# 聚焦联赛过滤 (2026-08-16 起: 只关注五大联赛)
try:
    from config import FOCUS_LEAGUES
    before = len(today)
    today = [m for m in today if m.get('league_code') in FOCUS_LEAGUES]
    print(f'聚焦联赛过滤: {before} → {len(today)} 场 (保留 {FOCUS_LEAGUES})')
except Exception as e:
    print(f'聚焦联赛过滤跳过: {e}')

pathlib.Path('data/today.json').write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nSaved {len(today)} matches to data/today.json')

# Also save Kambi in pinnacle-compatible format
pinnacle_format = []
for m in all_today:
    if m['id'] not in kambi_data:
        continue
    home = NAME_FIX.get(m['home'], m['home'])
    away = NAME_FIX.get(m['away'], m['away'])
    o = kambi_data[m['id']]
    pinnacle_format.append({
        'home_team': home,
        'away_team': away,
        'bookmakers': [{'key': 'pinnacle', 'markets': [
            {'key': 'h2h', 'outcomes': [
                {'name': home, 'price': o['home']},
                {'name': 'Draw', 'price': o['draw']},
                {'name': away, 'price': o['away']},
            ]}
        ]}]
    })

odds_path = pathlib.Path(f'data/pinnacle_odds_{target_date}.json')
odds_path.write_text(json.dumps(pinnacle_format, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Saved {len(pinnacle_format)} odds entries to {odds_path}')

# Summary
with_odds = sum(1 for m in today if m.get('odds'))
without_odds = [(m['home_team'], m['away_team'], m['league_code']) for m in today if not m.get('odds')]
print(f'\n=== SUMMARY ===')
print(f'Total matches in supported leagues: {len(today)}')
print(f'With Kambi odds: {with_odds}')
print(f'Without odds: {len(without_odds)}')
if without_odds:
    for h, a, lc in without_odds[:10]:
        print(f'  NO ODDS: {h} vs {a} ({lc})')
