"""Fetch bet365 odds — try multiple sources for 三线合并 (1X2+亚盘+大小球)"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import config

# ===== Source 1: 体彩 multi-pool =====
print('===== 体彩 多盘口 (HHAD/TTG) =====')
try:
    import httpx
    pool_codes = ['HAD', 'HHAD', 'TTG']
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.sporttery.cn/',
    }
    for pc in pool_codes:
        url = f'https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?poolCode={pc}&channelId=500'
        try:
            with httpx.Client(timeout=15, verify=False) as client:
                resp = client.get(url, headers=headers)
                print(f'{pc}: status={resp.status_code} len={len(resp.text)}')
                if resp.status_code == 200:
                    data = resp.json()
                    matches = data.get('value', {}).get('matchList', [])
                    print(f'  matches: {len(matches)}')
                    for m in matches[:5]:
                        home = m.get('homeTeam','?')
                        away = m.get('awayTeam','?')
                        odds = m.get('oddsList',{})
                        print(f'  {home} vs {away}')
                        for ok, ov in odds.items():
                            print(f'    {ok}: {json.dumps(ov, ensure_ascii=False)[:250]}')
        except Exception as e:
            print(f'{pc}: ERROR {e}')
        print()
except ImportError:
    print('httpx not available, trying urllib...')
    import urllib.request
    for pc in ['HAD', 'HHAD', 'TTG']:
        url = f'https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?poolCode={pc}&channelId=500'
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://www.sporttery.cn/',
            })
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode('utf-8'))
            matches = data.get('value', {}).get('matchList', [])
            print(f'{pc}: {len(matches)} matches')
            for m in matches[:5]:
                home = m.get('homeTeam','?')
                away = m.get('awayTeam','?')
                odds = m.get('oddsList',{})
                print(f'  {home} vs {away}')
                for ok, ov in odds.items():
                    print(f'    {ok}: {json.dumps(ov, ensure_ascii=False)[:200]}')
        except Exception as e:
            print(f'{pc}: ERROR {e}')
        print()
