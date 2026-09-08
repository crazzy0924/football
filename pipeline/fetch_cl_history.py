# -*- coding: utf-8 -*-
"""拉取欧冠(UCL)历史赛果 football-data.org → data/historical_odds/CL_<season>.csv"""
from __future__ import annotations
import csv, io, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from config import FOOTBALL_DATA_API_KEY

API = 'https://api.football-data.org/v4/competitions/CL/matches'
SEASONS = [2023, 2024, 2025]  # 2023/24, 2024/25, 2025/26

def _goals90(score):
    """取 90 分钟比分 (加时赛只算常规时间, 符合胜平负口径)"""
    if not score:
        return None, None
    rt = score.get('regularTime')
    src = rt if rt else score.get('fullTime')
    if not src:
        return None, None
    return src.get('home'), src.get('away')

def fetch_season(season):
    headers = {'X-Auth-Token': FOOTBALL_DATA_API_KEY}
    import httpx
    rows = []
    offset = 0
    while True:
        params = {'season': str(season), 'status': 'FINISHED', 'limit': 500}
        with httpx.Client(timeout=30) as c:
            r = c.get(API, params=params, headers=headers)
        if r.status_code == 429:
            print('  限流, 跳过 offset ' + str(offset))
            break
        if r.status_code != 200:
            print('  HTTP ' + str(r.status_code) + ' ' + r.text[:100])
            break
        j = r.json()
        for m in j.get('matches', []):
            h, a = _goals90(m.get('score'))
            if h is None or a is None:
                continue
            date = (m.get('utcDate') or '')[:10]
            home = (m.get('homeTeam') or {}).get('name', '').strip()
            away = (m.get('awayTeam') or {}).get('name', '').strip()
            if not home or not away:
                continue
            ftr = 'H' if h > a else ('D' if h == a else 'A')
            rows.append({'Date': date, 'HomeTeam': home, 'AwayTeam': away, 'FTHG': h, 'FTAG': a, 'FTR': ftr})
        rs = j.get('resultSet') or {}
        total = rs.get('count', 0)
        # football-data.org v4 该端点通常一次返回全部; 若 count 达到 limit 且还有更多则翻页
        if total >= 500:
            offset += 500
            continue
        break
    return rows

def main():
    if not FOOTBALL_DATA_API_KEY:
        print('未配置 FOOTBALL_DATA_API_KEY')
        return
    outdir = 'data/historical_odds'
    os.makedirs(outdir, exist_ok=True)
    for s in SEASONS:
        rows = fetch_season(s)
        # 去重(同一场可能因分页/重跑重复)
        seen = set()
        uniq = []
        for r in rows:
            k = (r['Date'], r['HomeTeam'], r['AwayTeam'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        short = str(s)[-2:] + str(s+1)[-2:]
        fname = 'CL_' + short + '.csv'
        path = os.path.join(outdir, fname)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['Div','Date','HomeTeam','AwayTeam','FTHG','FTAG','FTR'])
            w.writeheader()
            for r in uniq:
                w.writerow({'Div':'CL','Date':r['Date'],'HomeTeam':r['HomeTeam'],'AwayTeam':r['AwayTeam'],'FTHG':r['FTHG'],'FTAG':r['FTAG'],'FTR':r['FTR']})
        print('赛季 %d/%d: %d 场 → %s' % (s, s+1, len(uniq), path))

if __name__ == '__main__':
    main()