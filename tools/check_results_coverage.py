# -*- coding: utf-8 -*-
"""检查赛果覆盖: 每个预测过的比赛, 能不能在当天的赛果文件里找到?

用途: 每次清理/重新拉取赛果后跑一遍, 确保没有把"可结算比赛"弄丢。
      --against 可指定对照组(如清理前的备份)做前后对比。

用法:
    python tools/check_results_coverage.py
    python tools/check_results_coverage.py --against data/output/_backup_results
"""
import argparse
import json
import os
import re
import glob

STOP = {'fc', 'cf', 'sc', 'afc', 'sk', 'fk', 'ac', 'as', 'ss', 'cd', 'sv',
        'vfb', 'vfl', 'tsg', 'bsc', 'osc', 'us', 'club', 'de', 'city'}
KEYS = {'UCL', 'UEL', 'PL', 'PD', 'BL1', 'SA', 'FL1', 'ELC'}


def _toks(s):
    return [t for t in re.sub(r'[^a-z0-9 ]', ' ', str(s or '').lower()).split()
            if len(t) >= 3 and t not in STOP]


def _lvl(s):
    x = str(s or '')
    m = []
    if re.search(r'\bU1[4-9]\b|\bU2[0-3]\b', x, re.I):
        m.append('y')
    if re.search(r'\bII\b|reserve', x, re.I):
        m.append('r')
    if re.search(r'\bW\b|women', x, re.I):
        m.append('w')
    return ','.join(sorted(m))


def _sim(a, b):
    A, B = _toks(a), _toks(b)
    h = 0
    for t in A:
        if any(u == t or (len(t) >= 5 and u.find(t) >= 0) or (len(u) >= 5 and t.find(u) >= 0) for u in B):
            h += 1
    return h


def _find(res, ph, pa):
    best, bs = None, 0
    for x in res:
        if _lvl(x.get('home_team')) != _lvl(ph) or _lvl(x.get('away_team')) != _lvl(pa):
            continue
        s1, s2 = _sim(ph, x.get('home_team')), _sim(pa, x.get('away_team'))
        if s1 >= 1 and s2 >= 1 and s1 + s2 > bs:
            bs, best = s1 + s2, x
    return best


def measure(results_dir):
    hit = miss = 0
    missing = []
    for fp in sorted(glob.glob('data/output/predictions_????-??-??.json')):
        date = os.path.basename(fp)[12:22]
        rf = os.path.join(results_dir, 'results_%s.json' % date)
        if not os.path.exists(rf):
            continue
        res = json.load(open(rf, encoding='utf-8'))
        for p in json.load(open(fp, encoding='utf-8')):
            if p.get('league_code') not in KEYS:
                continue
            if _find(res, p['home_team'], p['away_team']):
                hit += 1
            else:
                miss += 1
                missing.append('%s %s vs %s [%s]' % (date, p['home_team'], p['away_team'],
                                                     p.get('league_code')))
    return hit, miss, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--against', default=None, help='对照组目录(如清理前的备份)')
    a = ap.parse_args()

    base = a.against or 'data/output/_backup_results'
    h1, m1, _ = measure(base)
    h2, m2, x2 = measure('data/output')
    print('对照 %s : 命中 %d, 未命中 %d' % (base, h1, m1))
    print('当前 data/output  : 命中 %d, 未命中 %d' % (h2, m2))
    if m2 > m1:
        print('')
        print('[FAIL] 丢失 %d 场可结算比赛:' % (m2 - m1))
        for s in x2[:20]:
            print('   ' + s)
        raise SystemExit(1)
    print('')
    print('[OK] 没有丢失任何可结算比赛')


if __name__ == '__main__':
    main()
