# -*- coding: utf-8 -*-
"""从 SofaScore 抓取真实盘口 (Playwright + 系统 Edge 过反爬)
  取: 1X2 + 大小球(动态线 0.5/1.5/2.5/3.5...) + 亚盘"""
from __future__ import annotations
import json, os, sys, io, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API = 'https://api.sofascore.com/api/v1'

def _frac(f):
    if not f: return None
    try:
        a, b = f.split('/')
        return round(1 + int(a) / int(b), 3)
    except Exception: return None

def _j(pg, url):
    return pg.evaluate('''async (u) => { const r = await fetch(u, {headers:{'x-requested-with':'XMLHttpRequest'}}); return r.ok ? await r.json() : null; }''', url)

def parse_odds(body):
    o = {'home': None, 'draw': None, 'away': None, 'ou': {}, 'ah': None}
    for m in (body or {}).get('markets', []):
        mg, mp = m.get('marketGroup'), m.get('marketPeriod')
        if mg == '1X2' and mp == 'Full-time':
            for c in m.get('choices', []):
                d = _frac(c.get('fractionalValue'))
                n = c.get('name')
                if n == '1': o['home'] = d
                elif n == 'X': o['draw'] = d
                elif n == '2': o['away'] = d
        elif mg == 'Match goals':
            line = m.get('choiceGroup')
            if line:
                s = o['ou'].setdefault(line, {})
                for c in m.get('choices', []):
                    s[c.get('name')] = _frac(c.get('fractionalValue'))
        elif mg == 'Asian Handicap':
            names = [c.get('name') for c in m.get('choices', [])]
            o['ah'] = names
    return o

def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel='msedge')
        ctx = b.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36')
        pg = ctx.new_page()
        pg.goto('https://www.sofascore.com/football', timeout=30000, wait_until='domcontentloaded')
        pg.wait_for_timeout(4000)
        # 1) 首页比赛 event id
        ids = pg.evaluate('''() => {
            const s = new Set();
            document.querySelectorAll('a[href*="/football/match/"]').forEach(a => {
                const m = (a.getAttribute('href')||'').match(/#id:(\\d+)/);
                if (m) s.add(m[1]);
            });
            return Array.from(s);
        }''')
        print('首页比赛 %d 场' % len(ids))
        out = {}
        for eid in ids:
            try:
                det = _j(pg, API + '/event/' + eid)
                if not det: continue
                e = det.get('event', {})
                home = (e.get('homeTeam') or {}).get('name', '')
                away = (e.get('awayTeam') or {}).get('name', '')
                lg = (e.get('tournament') or {}).get('name', '')
                ts = e.get('startTimestamp')
                if not home or not away: continue
                time.sleep(0.4)  # 防限流
                ob = _j(pg, API + '/event/%s/odds/1/all' % eid)
                odds = parse_odds(ob)
                key = home + ' vs ' + away
                out[key] = {'event_id': int(eid), 'league': lg, 'home': home, 'away': away, 'start_ts': ts, 'odds': odds}
                ou25 = odds['ou'].get('2.5', {})
                print('  %s vs %s [%s] | 1X2 %s/%s/%s | 2.5 大%s/小%s' % (home, away, lg, odds['home'], odds['draw'], odds['away'], ou25.get('Over'), ou25.get('Under')))
            except Exception as _e:
                print('  跳过 %s: %s' % (eid, str(_e)[:60]))
        b.close()
    os.makedirs('data/state', exist_ok=True)
    path = 'data/state/sofascore_odds.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('已保存 %d 场 → %s' % (len(out), path))

if __name__ == '__main__':
    main()