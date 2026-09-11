# -*- coding: utf-8 -*-
"""从 SofaScore 抓取真实盘口 (Playwright + 系统 Edge 过反爬)。

取: 1X2 + 大小球(动态阶梯 0.5/1.5/2.5/3.5...) + 亚盘。

2026-09-11 重写:
  - 旧版只从 sofascore.com/football 首页扒链接, 一天只能拿到 40 来场, 且混进
    UEFA Youth League 等青年队比赛 → 覆盖面远不够"每场都有大小球"。
  - 改为走联赛 API: unique-tournament/{id}/seasons 拿当前赛季
    → /events/next/0 + /events/last/0 拿整轮赛程(含日期)
    → 按日期过滤 → 逐个取盘口。
  - **只保留五大联赛 + 欧冠**, 并按级别标签剔除青年队/预备队/女足。

用法:
    python pipeline/odds_fetcher_sofascore.py                # 今天
    python pipeline/odds_fetcher_sofascore.py 2026-09-12     # 指定日期
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API = 'https://api.sofascore.com/api/v1'

# SofaScore 联赛 id → 我们的联赛代码 (只做这些, 其余一律不取)
TOURNAMENTS = [
    (17, 'PL',  'Premier League'),
    (8,  'PD',  'LaLiga'),
    (35, 'BL1', 'Bundesliga'),
    (23, 'SA',  'Serie A'),
    (34, 'FL1', 'Ligue 1'),
    (7,  'UCL', 'Champions League'),
]

# 级别标签: 青年队 / 预备队 / 女足 —— 一律剔除 (2026-09-11 用户要求)
_LEVEL_PATTERNS = [
    re.compile(r'\bU\s?1[4-9]\b'), re.compile(r'\bU\s?2[0-3]\b'),
    re.compile(r'youth', re.I), re.compile(r'\bII\b'), re.compile(r'reserve', re.I),
    re.compile(r'\bwomen\b', re.I), re.compile(r'\bW\b'),
]


def is_youth_or_reserve(*names: str) -> bool:
    return any(p.search(n or '') for n in names for p in _LEVEL_PATTERNS)


def _frac(f):
    if not f:
        return None
    try:
        a, b = f.split('/')
        return round(1 + int(a) / int(b), 3)
    except Exception:
        return None


def _j(pg, url, retries: int = 3):
    """调 SofaScore JSON 接口。JS 侧带 try/catch + Python 侧重试退避,
    否则一次网络抖动/限流就会把整轮抓取打断。"""
    for i in range(retries):
        try:
            r = pg.evaluate(
                """async (u) => { try { const r = await fetch(u, {headers:{'x-requested-with':'XMLHttpRequest'}});
                          if (!r.ok) return {__err: r.status};
                          return await r.json(); } catch (e) { return {__err: String(e)}; } }""",
                url,
            )
        except Exception:
            r = None
        if isinstance(r, dict) and '__err' in r:
            if i == retries - 1:
                print('   [接口] %s -> %s' % (url.split('/api/v1')[-1][:70], r['__err']))
            time.sleep(1.5 * (i + 1))
            continue
        if r is not None:
            return r
        time.sleep(1.5 * (i + 1))
    return None


def parse_odds(body):
    """盘口解析: 1X2 + Match goals 全阶梯 + 亚盘。"""
    o = {'home': None, 'draw': None, 'away': None, 'ou': {}, 'ah': None}
    for m in (body or {}).get('markets', []):
        mg, mp = m.get('marketGroup'), m.get('marketPeriod')
        if mg == '1X2' and mp == 'Full-time':
            for c in m.get('choices', []):
                d = _frac(c.get('fractionalValue'))
                n = c.get('name')
                if n == '1':
                    o['home'] = d
                elif n == 'X':
                    o['draw'] = d
                elif n == '2':
                    o['away'] = d
        elif mg == 'Match goals':
            line = m.get('choiceGroup')
            if line:
                s = o['ou'].setdefault(line, {})
                for c in m.get('choices', []):
                    s[c.get('name')] = _frac(c.get('fractionalValue'))
        elif mg == 'Asian Handicap':
            names = [c.get('name') for c in m.get('choices', [])]
            o['ah'] = names
        elif mg == 'Both teams to score':
            # 2026-09-11 新增: 体彩没有双进球玩法(只有 HAD/HHAD/TTG/CRS/HAFU),
            # 只有外围有。漏了这个市场就没法做"模型 BTTS vs 市场 BTTS"的 edge 对比。
            d = o.setdefault('btts', {})
            for c in m.get('choices', []):
                n = (c.get('name') or '').strip().lower()
                if n in ('yes', 'no'):
                    d[n] = _frac(c.get('fractionalValue'))
        elif mg == 'Double chance':
            d = o.setdefault('dc', {})
            for c in m.get('choices', []):
                d[(c.get('name') or '').strip()] = _frac(c.get('fractionalValue'))
        elif mg == 'Draw no bet':
            d = o.setdefault('dnb', {})
            for c in m.get('choices', []):
                d[(c.get('name') or '').strip()] = _frac(c.get('fractionalValue'))
    return o


def list_matchday(pg, tid, code, days):
    """某联赛在指定日期(可多天)的比赛 [(event_id, home, away, ts)]。

    2026-09-11 修复: 原先只查单日。但 21:00 的终盘预测的是**次日凌晨**的比赛
    (欧洲晚上 = 北京次日 02:30~03:00), 单日查询会把整批五大联赛全漏掉 ——
    当天实测只抓到 6 场欧冠, 五大一场没有。改成日期窗口即可覆盖交界情况。
    """
    if isinstance(days, str):
        days = {days}
    seasons = (_j(pg, '%s/unique-tournament/%d/seasons' % (API, tid)) or {}).get('seasons') or []
    if not seasons:
        print('  %s: 拿不到赛季列表' % code)
        return []
    sid = seasons[0]['id']
    seen = {}
    for page in ('next/0', 'last/0'):
        body = _j(pg, '%s/unique-tournament/%d/season/%s/events/%s' % (API, tid, sid, page)) or {}
        for e in body.get('events') or []:
            ts = e.get('startTimestamp')
            if not ts:
                continue
            if datetime.fromtimestamp(ts).strftime('%Y-%m-%d') not in days:
                continue
            h = (e.get('homeTeam') or {}).get('name', '')
            a = (e.get('awayTeam') or {}).get('name', '')
            if not h or not a:
                continue
            seen[e['id']] = (h, a, ts)
        time.sleep(0.3)
    return [(eid, h, a, ts) for eid, (h, a, ts) in seen.items()]


def archive_snapshot(day, stage, out):
    """把本次抓取存进 data/state/ou_history/<日期>.json (按节点保留, 可看盘口移动)。

    sofascore_odds.json 是"当日最新", 每天被覆盖 → 没有历史。
    这里按节点留档: 同一天多次抓取(午盘/终盘)都保留, 便于回看临场线怎么变。
    """
    d = os.path.join('data', 'state', 'ou_history')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, day + '.json')
    rec = {'date': day, 'snapshots': []}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except Exception:
            pass
    snaps = [s for s in rec.get('snapshots', []) if s.get('stage') != stage]
    snaps.append({
        'stage': stage,
        'taken_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'n_matches': len(out),
        'matches': out,
    })
    snaps.sort(key=lambda s: s.get('taken_at', ''))
    rec['snapshots'] = snaps
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    return path


def main():
    import argparse
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser(description='SofaScore 五大+欧冠盘口抓取')
    ap.add_argument('date', nargs='?', default=datetime.now().strftime('%Y-%m-%d'))
    ap.add_argument('--stage', default='manual', choices=['midday', 'final', 'manual'],
                    help='抓取节点, 用于留档区分 (午盘/终盘)')
    ap.add_argument('--window', type=int, default=1,
                    help='日期窗口(天): 前后各取 N 天, 覆盖"欧洲晚上=北京次日凌晨"的交界 (默认1)')
    a = ap.parse_args()
    day, stage = a.date, a.stage
    # 日期窗口: 终盘预测的常是次日凌晨的比赛, 只看当天会整批漏掉
    base = datetime.strptime(day, '%Y-%m-%d')
    days = {(base + timedelta(days=d)).strftime('%Y-%m-%d')
            for d in range(-a.window, a.window + 1)}
    print('日期窗口: %s' % ' '.join(sorted(days)))

    out = {}
    skipped_youth = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel='msedge')
        ctx = b.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/125.0 Safari/537.36'))
        pg = ctx.new_page()
        pg.goto('https://www.sofascore.com/football', timeout=45000, wait_until='domcontentloaded')
        pg.wait_for_timeout(3000)

        total_matches = 0
        for tid, code, name in TOURNAMENTS:
            games = list_matchday(pg, tid, code, days)
            print('%s %s: 窗口内 %d 场' % (code, name, len(games)))
            total_matches += len(games)
            for eid, home, away, ts in games:
                if is_youth_or_reserve(home, away):
                    skipped_youth += 1
                    continue
                try:
                    time.sleep(0.35)
                    ob = _j(pg, '%s/event/%s/odds/1/all' % (API, eid))
                    odds = parse_odds(ob)
                except Exception as e:
                    print('   跳过 %s vs %s: %s' % (home, away, str(e)[:50]))
                    continue
                if not odds.get('ou'):
                    print('   %s vs %s: 无大小球盘口' % (home, away))
                out[home + ' vs ' + away] = {
                    'event_id': int(eid), 'league': name, 'league_code': code,
                    'home': home, 'away': away, 'start_ts': ts, 'odds': odds,
                }
        b.close()

    os.makedirs('data/state', exist_ok=True)
    path = 'data/state/sofascore_odds.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    with_ou = sum(1 for v in out.values() if v['odds'].get('ou'))
    hist = archive_snapshot(day, stage, out)
    print('')
    print('当日五大+欧冠共 %d 场; 剔除青年/预备/女足 %d 场' % (total_matches, skipped_youth))
    print('已保存 %d 场 → %s (其中 %d 场有大小球)' % (len(out), path, with_ou))
    print('已留档 → %s (节点: %s)' % (hist, stage))


if __name__ == '__main__':
    main()
