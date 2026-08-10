"""Fetch Pinnacle odds from odds-api.io v3"""
import httpx, json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import config

key = config.ODDS_API_IO_KEY
event_ids = [67126688, 67126690, 72530832]  # Sirius, Vasteras, Santa Clara
event_names = {
    67126688: 'IK Sirius vs IF Brommapojkarna',
    67126690: 'Vasteraas SK vs Djurgardens IF',
    72530832: 'Santa Clara Azores vs Nacional da Madeira',
}
base = 'https://api.odds-api.io/v3'
all_odds = []

with httpx.Client(timeout=15, verify=False) as client:
    for eid in event_ids:
        url = f'{base}/odds?apiKey={key}&eventId={eid}'
        resp = client.get(url)
        print(f'[{eid}] {event_names[eid]}: HTTP {resp.status_code}')
        if resp.status_code == 200:
            data = resp.json()
            # Show bookmakers available
            if isinstance(data, dict):
                bookmakers = data.get('bookmakers', data.get('data', []))
                if isinstance(bookmakers, list):
                    bm_names = [b.get('name', b.get('key','?')) for b in bookmakers]
                    print(f'  Bookmakers: {bm_names}')

                    # Look for Pinnacle
                    for bm in bookmakers:
                        name = bm.get('name', bm.get('key',''))
                        if 'pinnacle' in name.lower() or 'pin' in name.lower():
                            print(f'  >> PINNACLE FOUND: {name}')
                            print(json.dumps(bm, indent=2, ensure_ascii=False)[:1500])

                    # If no Pinnacle, show first bookmaker's structure
                    if not any('pinnacle' in b.get('name','').lower() + b.get('key','').lower() for b in bookmakers):
                        print(f'  First bookmaker: {json.dumps(bookmakers[0], indent=2, ensure_ascii=False)[:800]}')
                else:
                    print(f'  Data type: {type(bookmakers)}')
                    print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            all_odds.append(data)
        else:
            print(f'  Error: {resp.text[:200]}')
        print()

# Save raw data
pathlib.Path('data/pinnacle_raw_2026-08-10.json').write_text(
    json.dumps(all_odds, indent=2, ensure_ascii=False), encoding='utf-8')
print('Saved to data/pinnacle_raw_2026-08-10.json')
