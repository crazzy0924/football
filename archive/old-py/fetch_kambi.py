"""拉取Kambi赔率(通过Unibet)并生成终盘预测"""
import requests, json, os, time
from datetime import datetime
from pathlib import Path

env_path = Path(__file__).resolve().parent / '.env'
KEY = ''
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        if line.startswith('ODDS_API_IO_KEY='):
            KEY = line.split('=', 1)[1].strip()
            break

BOOKMAKER = 'Unibet'  # Kambi引擎的博彩公司

# 1. 拉取足球赛事
print("Fetching events...")
r = requests.get('https://api.odds-api.io/v3/events', params={
    'sport': 'football', 'bookmaker': BOOKMAKER, 'apiKey': KEY
}, timeout=20)
events = r.json()

# 2. 筛选欧联/欧协联资格赛
target_leagues = ['Europa League', 'Conference League', 'Champions League Qual']
matches = []
for e in events:
    ln = e.get('league', {}).get('name', '')
    if any(t in ln for t in target_leagues):
        matches.append(e)

print(f"Target matches: {len(matches)}")

# 3. 拉取赔率 (正确解析)
print("Fetching odds...")
for i, m in enumerate(matches):
    try:
        time.sleep(0.15)
        r2 = requests.get('https://api.odds-api.io/v3/odds', params={
            'eventId': m['id'], 'bookmakers': BOOKMAKER, 'apiKey': KEY
        }, timeout=15)
        data = r2.json()

        # 新结构: bookmakers.Unibet = [{"name":"ML","odds":[{"home":"1.10","draw":"9.00","away":"19.00"}]}]
        bms = data.get('bookmakers', {})
        if isinstance(bms, dict):
            for bm_name, markets in bms.items():
                if isinstance(markets, list):
                    for mkt in markets:
                        if mkt.get('name') in ('ML', '1X2', 'Full Time Result'):
                            odds_list = mkt.get('odds', [])
                            if odds_list:
                                o = odds_list[0]
                                m['odds_1x2'] = {
                                    'home': float(o.get('home', 0)),
                                    'draw': float(o.get('draw', 0)),
                                    'away': float(o.get('away', 0)),
                                }
                                m['odds_source'] = f'{BOOKMAKER} (Kambi)'
                                print(f"  {m['home'][:20]} vs {m['away'][:20]}: {m['odds_1x2']}")
                                break
    except Exception as e:
        print(f"  {m['home'][:20]}: ERROR - {str(e)[:50]}")

# 保存
out_path = Path('data/kambi_odds.json')
out_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
with_odds = sum(1 for m in matches if m.get('odds_1x2'))
print(f"\nSaved {len(matches)} matches ({with_odds} with Unibet odds) to {out_path}")
