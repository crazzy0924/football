# -*- coding: utf-8 -*-
"""多维度 ROI 回测: 1X2 / 大小球2.5 / 亚盘, 全部对标 Pinnacle 真实赔率。

为什么: "跑赢常数基准"不等于"能赚钱"。真正的裁判是市场。
       大小球已测出全亏, 这里补上表现最好的两个维度(1X2 与让球)。

数据: data/historical_odds/*.csv
      1X2   -> PSH/PSD/PSA (缺失回退 B365H/D/A)
      大小球 -> P>2.5 / P<2.5
      亚盘   -> AHh + PAHH/PAHA
做法: 早期赛季训练 -> 样本外测试 -> 按 |模型-市场公平概率| 阈值平注

亚盘结算: 含走盘(退本金)与四分之一球(半注半注拆开)

用法: python tools/backtest_roi.py [测试赛季, 默认 2526]
"""
import csv
import glob
import io
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.dixon_coles import DixonColesModel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data', 'historical_odds')
CSV_CODE = {'PL': 'E0', 'PD': 'SP1', 'BL1': 'D1', 'SA': 'I1', 'FL1': 'F1'}
CAL_W = 0.5


def norm_season(s):
    s = (s or '').strip()
    if len(s) == 4 and s.isdigit():
        y = int(s)
        if 2000 < y < 2100:
            return '%02d%02d' % (y % 100, (y + 1) % 100)
    return s


def f(v):
    try:
        return float(v)
    except Exception:
        return None


def devig(*odds):
    """去水: 返回公平概率列表 (含 0/None 的项按原样保留份额为 0)。"""
    inv = [1.0 / o if o else 0.0 for o in odds]
    s = sum(inv)
    return [x / s for x in inv] if s > 0 else [0.0] * len(odds)


def settle_ah(h, a, line, side, odds):
    """亚盘结算, 返回盈亏 (平注 1 单位)。

    side='home': 主队让 line (line 通常为负)。四分之一球拆半注。
    """
    def one(ln):
        diff = (h + ln) - a
        if diff > 0:
            return (odds - 1.0) if side == 'home' else -1.0
        if diff < 0:
            return -1.0 if side == 'home' else (odds - 1.0)
        return 0.0   # 走盘

    q = round(abs(line - round(line * 2) / 2), 4)
    if q == 0.25:                       # 四分之一球: 拆两条线
        return 0.5 * one(line - 0.25) + 0.5 * one(line + 0.25)
    return one(line)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    use_mle = '--mle' in sys.argv
    test = norm_season(args[0]) if args else '2526'
    per = defaultdict(list)
    for lg, code in CSV_CODE.items():
        for fp in sorted(glob.glob(os.path.join(HIST, code + '_*'))):
            if not fp.lower().endswith('.csv'):
                continue
            season = norm_season(os.path.basename(fp).split('_')[-1].rsplit('.', 1)[0])
            try:
                with io.open(fp, encoding='utf-8-sig') as fh:
                    for row in csv.DictReader(fh):
                        try:
                            h, a = int(row['FTHG']), int(row['FTAG'])
                        except Exception:
                            continue
                        hh = (row.get('HomeTeam') or '').strip()
                        aa = (row.get('AwayTeam') or '').strip()
                        if not hh or not aa:
                            continue
                        per[lg].append({
                            'season': season, 'home': hh, 'away': aa, 'h': h, 'a': a,
                            'home_team': hh, 'away_team': aa,
                            'home_goals': h, 'away_goals': a,
                            'result': 'H' if h > a else ('D' if h == a else 'A'),
                            'oh': f(row.get('PSH')) or f(row.get('B365H')),
                            'od': f(row.get('PSD')) or f(row.get('B365D')),
                            'oa': f(row.get('PSA')) or f(row.get('B365A')),
                            'ov': f(row.get('P>2.5')) or f(row.get('B365>2.5')),
                            'un': f(row.get('P<2.5')) or f(row.get('B365<2.5')),
                            'ahl': f(row.get('AHh')),
                            'ahh': f(row.get('PAHH')) or f(row.get('B365AHH')),
                            'aha': f(row.get('PAHA')) or f(row.get('B365AHA')),
                        })
            except Exception:
                continue
    tr, te = [], []
    for lg, ms in per.items():
        for m in ms:
            m2 = dict(m)
            m2['league_code'] = lg
            (te if m['season'] == test else tr).append(m2)
    print('训练 %d 场, 测试 %d 场  拟合方式=%s' % (len(tr), len(te), 'MLE(生产同款)' if use_mle else 'fit_simple(解析)'))
    dc = DixonColesModel()
    if use_mle:
        # 2026-09-11: 生产环境用 MLE, 而首跑用的是 fit_simple —— 可能低估了模型。
        # 这个开关就是为了消除这个怀疑: 换成生产同款拟合再跑一次。
        dc.fit_mle(tr)
    else:
        dc.fit_simple(tr)
    base = {}
    for lg in CSV_CODE:
        g = [m for m in tr if m['league_code'] == lg]
        if g:
            base[lg] = sum(1 for m in g if m['h'] + m['a'] > 2.5) / len(g)

    th_list = (0.03, 0.05, 0.08, 0.10)
    res = {d: {t: {'n': 0, 'w': 0, 'pnl': 0.0} for t in th_list} for d in ('1X2', 'OU25', 'AH')}

    for m in te:
        try:
            r = dc.predict(m['home'], m['away'], m['league_code'])
        except Exception:
            continue
        if not r or not r.get('score_distribution'):
            continue
        h, a = m['h'], m['a']
        res_ = 'H' if h > a else ('D' if h == a else 'A')
        # 1X2
        if m['oh'] and m['od'] and m['oa']:
            fair = devig(m['oh'], m['od'], m['oa'])
            mod = [r['home_win'], r['draw'], r['away_win']]
            odds = [m['oh'], m['od'], m['oa']]
            labels = ['H', 'D', 'A']
            for i in range(3):
                e = mod[i] - fair[i]
                win = (labels[i] == res_)
                for t in th_list:
                    if abs(e) >= t:
                        res['1X2'][t]['n'] += 1
                        gain = (odds[i] - 1.0) if win else -1.0
                        res['1X2'][t]['pnl'] += gain
                        res['1X2'][t]['w'] += (gain > 0)
        # 大小球
        if m['ov'] and m['un']:
            p = CAL_W * r['over_25'] + (1 - CAL_W) * base.get(m['league_code'], 0.534)
            fair = devig(m['ov'], m['un'])[0]
            e = p - fair
            ao = (h + a) > 2.5
            for t in th_list:
                if abs(e) >= t:
                    res['OU25'][t]['n'] += 1
                    gain = ((m['ov'] - 1.0) if ao else -1.0) if e > 0 else ((m['un'] - 1.0) if not ao else -1.0)
                    res['OU25'][t]['pnl'] += gain
                    res['OU25'][t]['w'] += (gain > 0)
        # 亚盘
        if m['ahl'] is not None and m['ahh'] and m['aha']:
            from pipeline.five_dim_predictor import compute_handicap_probs
            hp = compute_handicap_probs(r['score_distribution'], m['ahl'])
            ph, pp = hp['home_cover'], hp['push']
            fair = devig(m['ahh'], m['aha'])
            for side, pm, om in (('home', ph, m['ahh']), ('away', hp['away_cover'], m['aha'])):
                # 有走盘时按 (1-push) 归一
                p = pm / (1.0 - pp) if pp < 0.999 else pm
                e = p - fair[0 if side == 'home' else 1]
                for t in th_list:
                    if abs(e) >= t:
                        res['AH'][t]['n'] += 1
                        gain = settle_ah(h, a, m['ahl'], side, om)
                        res['AH'][t]['pnl'] += gain
                        res['AH'][t]['w'] += (gain > 0)

    for dim in ('1X2', 'OU25', 'AH'):
        print('')
        print('=== %s ===' % dim)
        print('  %-8s %-8s %-9s %-9s %s' % ('阈值', '注数', '命中率', 'P&L', 'ROI'))
        for t in th_list:
            v = res[dim][t]
            if not v['n']:
                print('  %-8.2f %-8d 无符合场次' % (t, 0))
                continue
            print('  %-8.2f %-8d %-9s %-9.2f %s' % (
                t, v['n'], '%.1f%%' % (v['w'] / v['n'] * 100), v['pnl'],
                '%+.1f%%' % (v['pnl'] / v['n'] * 100)))


if __name__ == '__main__':
    main()
