# -*- coding: utf-8 -*-
"""大小球 ROI 回测: 模型 edge 到底能不能赚钱 (对标 Pinnacle 真实赔率)。

为什么重要: "方向命中率跑赢常数基准" 不等于 "能赚钱"。
           真正的裁判是市场, 不是常数。

数据: data/historical_odds/*.csv 里的 P>2.5 / P<2.5 (Pinnacle), 缺失回退 Bet365。
做法: 早期赛季训练 -> 指定赛季样本外测试 -> 按 |模型-市场公平概率| 阈值平注。

用法: python tools/backtest_ou_roi.py [测试赛季, 默认 2526]

【2026-09-11 首跑结论】全亏, 且 edge 越大亏得越多 —— 模型在总进球上打不过市场。
  阈值3%  1230注 44.7% ROI -3.8%
  阈值5%   878注 44.2% ROI -2.1%
  阈值8%   484注 43.4% ROI -2.7%
  阈值10%  291注 40.2% ROI -6.3%
  阈值15%   64注 28.1% ROI -25.4%
注意: 本回测用 fit_simple(解析拟合), 生产环境用 MLE, 会低估模型质量;
     但"edge 越大越亏"这个反向规律, 很难用拟合方式解释。
"""
import csv
import glob
import io
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


def main():
    test = norm_season(sys.argv[1]) if len(sys.argv) > 1 else '2526'
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
                            'ov': f(row.get('P>2.5')) or f(row.get('B365>2.5')),
                            'un': f(row.get('P<2.5')) or f(row.get('B365<2.5')),
                        })
            except Exception:
                continue
    tr, te = [], []
    for lg, ms in per.items():
        for m in ms:
            m2 = dict(m)
            m2['league_code'] = lg
            (te if m['season'] == test else tr).append(m2)
    print('训练 %d 场, 测试 %d 场' % (len(tr), len(te)))
    dc = DixonColesModel()
    dc.fit_simple(tr)
    base = {}
    for lg in CSV_CODE:
        g = [m for m in tr if m['league_code'] == lg]
        if g:
            base[lg] = sum(1 for m in g if m['h'] + m['a'] > 2.5) / len(g)

    print('')
    print('%-8s %-8s %-9s %-9s %-9s %s' % ('阈值', '注数', '命中率', 'P&L', 'ROI', '平均edge'))
    for th in (0.03, 0.05, 0.08, 0.10, 0.15):
        n = w = 0
        pnl = 0.0
        edges = []
        for m in te:
            o, u = m['ov'], m['un']
            if not o or not u:
                continue
            try:
                r = dc.predict(m['home'], m['away'], m['league_code'])
            except Exception:
                continue
            if not r or r.get('over_25') is None:
                continue
            p = CAL_W * r['over_25'] + (1 - CAL_W) * base.get(m['league_code'], 0.534)
            fair = (1.0 / o) / (1.0 / o + 1.0 / u)
            e = p - fair
            if abs(e) < th:
                continue
            ao = (m['h'] + m['a']) > 2.5
            n += 1
            edges.append(abs(e))
            gain = ((o - 1) if ao else -1.0) if e > 0 else ((u - 1) if not ao else -1.0)
            pnl += gain
            w += (gain > 0)
        if n:
            print('%-8.2f %-8d %-9s %-9.2f %-9s %.3f' % (
                th, n, '%.1f%%' % (w / n * 100), pnl, '%+.1f%%' % (pnl / n * 100),
                sum(edges) / len(edges)))
        else:
            print('%-8.2f %-8d 无符合场次' % (th, 0))


if __name__ == '__main__':
    main()
