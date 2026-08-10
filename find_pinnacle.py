import httpx, json, sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import config; key = config.ODDS_API_IO_KEY

with httpx.Client(timeout=15, verify=False) as client:
    url = f'https://api.odds-api.io/v3/bookmakers?apiKey={key}'
    resp = client.get(url)
    print(f'HTTP {resp.status_code} len={len(resp.text)}')
    if resp.status_code == 200:
        bookmakers = resp.json()
        if isinstance(bookmakers, list):
            print(f'Total bookmakers: {len(bookmakers)}')
            # Find Pinnacle
            for bm in bookmakers:
                s = json.dumps(bm).lower()
                if 'pinnacle' in s or 'pinny' in s:
                    print(f'  >> {json.dumps(bm, ensure_ascii=False)[:300]}')
            # Also search for 'pin'
            print('\nAll containing \"pin\":')
            for bm in bookmakers:
                if 'pin' in json.dumps(bm).lower():
                    print(f'  {bm.get("name")} | slug={bm.get("slug")}')
            # Save full list
            pathlib.Path('data/bookmakers_list.json').write_text(
                json.dumps(bookmakers, indent=2, ensure_ascii=False), encoding='utf-8')
            print('\nSaved full list to data/bookmakers_list.json')
