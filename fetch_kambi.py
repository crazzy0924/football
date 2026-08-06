"""拉取Kambi赔率并生成终盘预测"""
import requests, json, math, os
from datetime import datetime
from pathlib import Path

# 手动解析 .env (避免 dotenv 依赖)
env_path = Path(__file__).resolve().parent / '.env'
KEY = ''
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        if line.startswith('ODDS_API_IO_KEY='):
            KEY = line.split('=', 1)[1].strip()
            break

# 1. 拉取所有足球赛事
print("Fetching Kambi events...")
r = requests.get('https://api.odds-api.io/v3/events', params={
    'sport': 'football', 'bookmaker': 'Kambi', 'apiKey': KEY
}, timeout=20)
events = r.json()
print(f"Total events: {len(events)}")

# 2. 筛选欧联/欧协联资格赛
target_leagues = ['Europa League', 'Conference League', 'Champions League Qual']
matches = []
for e in events:
    ln = e.get('league', {}).get('name', '')
    if any(t in ln for t in target_leagues):
        matches.append(e)

print(f"Target matches: {len(matches)}")
for m in matches:
    print(f"  {m['home']} vs {m['away']} | {m.get('league',{}).get('name','')} | {m.get('date','')[:16]} | id={m['id']}")

# 3. 拉取赔率
print("\nFetching odds...")
for m in matches[:37]:
    try:
        r2 = requests.get('https://api.odds-api.io/v3/odds', params={
            'eventId': m['id'], 'bookmakers': 'Kambi', 'apiKey': KEY
        }, timeout=15)
        odds_data = r2.json()
        # odds_data结构: {"bookmakers": [{"markets": [{"name":"1X2","outcomes":[...]}]}]}
        if isinstance(odds_data, dict):
            bms = odds_data.get('bookmakers', odds_data.get('data', {}).get('bookmakers', []))
            if isinstance(bms, list):
                for bm in bms:
                    if isinstance(bm, dict):
                        markets = bm.get('markets', [])
                        if isinstance(markets, list):
                            for market in markets:
                                if isinstance(market, dict) and market.get('name') in ('1X2', 'Full Time Result'):
                                    outcomes = {o['name']: o['odds'] for o in market.get('outcomes', [])}
                                    m['odds_1x2'] = outcomes
                                    print(f"  {m['home']}: {outcomes}")
    except Exception as e:
        print(f"  {m['home']}: ERROR - {e}")

# 保存
with open('data/kambi_odds.json', 'w', encoding='utf-8') as f:
    json.dump(matches, f, ensure_ascii=False, indent=2, default=str)
print(f"\nSaved {len(matches)} matches to data/kambi_odds.json")
