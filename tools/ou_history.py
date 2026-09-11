# -*- coding: utf-8 -*-
"""大小球留档查询 (数据来自 data/state/ou_history/<日期>.json)。

用法:
    python tools/ou_history.py                      列出所有留档日期
    python tools/ou_history.py 2026-09-12           该日各节点 + 盘口移动
    python tools/ou_history.py 2026-09-12 利物浦     只看含关键词的场次
    python tools/ou_history.py --coverage           各日覆盖统计
"""
import argparse
import glob
import json
import os

HIST = os.path.join('data', 'state', 'ou_history')


def load(day):
    p = os.path.join(HIST, day + '.json')
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


def ou25(match):
    return (match.get('odds', {}).get('ou') or {}).get('2.5') or {}


def cmd_list():
    files = sorted(glob.glob(os.path.join(HIST, '*.json')))
    if not files:
        print('暂无留档 (先跑一次 pipeline/odds_fetcher_sofascore.py)')
        return
    print('%-12s %-10s %-22s %s' % ('日期', '快照数', '最后抓取', '有盘口场次'))
    for f in files:
        day = os.path.basename(f)[:-5]
        rec = load(day) or {}
        snaps = rec.get('snapshots') or []
        if not snaps:
            continue
        last = snaps[-1]
        n = last.get('n_matches', 0)
        w = sum(1 for m in (last.get('matches') or {}).values() if m.get('odds', {}).get('ou'))
        print('%-12s %-10d %-22s %d/%d' % (day, len(snaps), last.get('taken_at', '?'), w, n))


def cmd_day(day, kw=None):
    rec = load(day)
    if not rec:
        print('没有 %s 的留档' % day)
        return
    snaps = rec.get('snapshots') or []
    print('%s  共 %d 个节点' % (day, len(snaps)))
    for s in snaps:
        print('  [%-7s] %s  %d 场' % (s.get('stage', '?'), s.get('taken_at', '?'), s.get('n_matches', 0)))
    keys = list((snaps[0].get('matches') or {}).keys())
    if kw:
        keys = [k for k in keys if kw.lower() in k.lower()]
    print('')
    for k in keys:
        row = []
        for s in snaps:
            m = (s.get('matches') or {}).get(k)
            if not m:
                row.append('%s: -' % s.get('stage', '?'))
                continue
            o = ou25(m)
            row.append('%s: 线%s 大%s/小%s' % (s.get('stage', '?'), m.get('odds', {}).get('ou') and '2.5',
                                              o.get('Over'), o.get('Under')))
        print('  %-44s %s' % (k, '  |  '.join(row)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('date', nargs='?')
    ap.add_argument('kw', nargs='?')
    ap.add_argument('--coverage', action='store_true')
    a = ap.parse_args()
    if a.coverage or not a.date:
        cmd_list()
    else:
        cmd_day(a.date, a.kw)


if __name__ == '__main__':
    main()
