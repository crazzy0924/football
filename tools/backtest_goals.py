# -*- coding: utf-8 -*-
"""进球维度样本外回测 (大小球 / 双进球 / 总进球)。

为什么需要: 线上复盘样本只有 30 场, 判不了进球维度有没有区分度。
           历史 CSV 有 8957 场五大联赛, 可以做真正的样本外检验。

做法: 用早期赛季训练, 指定赛季测试 (默认 25/26), 报告
      - 各维度的 Brier 与方向命中率
      - "向联赛基准收缩" 不同权重下的表现 (用于确认线上校准参数)
      - 总进球最高档命中率 (TTG 玩法的基础)

用法:
    python tools/backtest_goals.py                # 默认测试 25/26
    python tools/backtest_goals.py 2425           # 换测试赛季
"""
import csv
import glob
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.dixon_coles import DixonColesModel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data', 'historical_odds')
CSV_CODE = {'PL': 'E0', 'PD': 'SP1', 'BL1': 'D1', 'SA': 'I1', 'FL1': 'F1'}


def norm_season(s: str) -> str:
    """赛季标签归一。五大用 E0_2025.csv(=25/26), 欧冠用 CL_2526.csv —— 两套写法。"""
    s = (s or '').strip()
    if len(s) == 4 and s.isdigit():
        y = int(s)
        if 2000 < y < 2100:
            return '%02d%02d' % (y % 100, (y + 1) % 100)
    return s


def load():
    per = defaultdict(list)
    for lg, code in CSV_CODE.items():
        for fp in sorted(glob.glob(os.path.join(HIST, code + '_*'))):
            if not fp.lower().endswith(('.csv', '.txt')):
                continue
            season = norm_season(os.path.basename(fp).split('_')[-1].rsplit('.', 1)[0])
            try:
                with io.open(fp, encoding='utf-8-sig') as f:
                    for row in csv.DictReader(f):
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
                        })
            except Exception:
                continue
    return per


def main():
    test = norm_season(sys.argv[1]) if len(sys.argv) > 1 else '2526'
    per = load()
    tr, te = [], []
    for lg, ms in per.items():
        for m in ms:
            m2 = dict(m)
            m2['league_code'] = lg
            (te if m['season'] == test else tr).append(m2)
    print('训练 %d 场, 测试 %d 场 (测试赛季 %s)' % (len(tr), len(te), test))
    if not te:
        print('测试集为空 —— 检查赛季标签')
        return

    dc = DixonColesModel()
    dc.fit_simple(tr)
    print('训练完成: %d 队, %d 联赛' % (len(dc.team_attack), len(dc.league_avg_goals)))

    # 训练集上算各联赛真实基准率 (样本外使用, 不循环)
    base = {}
    for lg in CSV_CODE:
        g = [m for m in tr if m['league_code'] == lg]
        if g:
            base[lg] = (sum(1 for m in g if m['h'] + m['a'] > 2.5) / len(g),
                        sum(1 for m in g if m['h'] > 0 and m['a'] > 0) / len(g))

    weights = (1.0, 0.8, 0.6, 0.5, 0.0)
    acc = {w: {'bo': 0.0, 'bb': 0.0, 'ho': 0, 'hb': 0} for w in weights}
    ok1x2 = 0
    b1x2 = 0.0
    tg_hit = tg_n = 0
    n = miss = 0
    for m in te:
        try:
            r = dc.predict(m['home'], m['away'], m['league_code'])
        except Exception:
            miss += 1
            continue
        if not r or not r.get('score_distribution'):
            miss += 1
            continue
        n += 1
        h, a = m['h'], m['a']
        res = 'H' if h > a else ('D' if h == a else 'A')
        probs = {'H': r['home_win'], 'D': r['draw'], 'A': r['away_win']}
        ok1x2 += (max(probs, key=probs.get) == res)
        b1x2 += sum((probs[k] - (1.0 if k == res else 0.0)) ** 2 for k in probs)

        ao, ab = (h + a) > 2.5, (h > 0 and a > 0)
        o0, b0 = base.get(m['league_code'], (0.534, 0.55))
        for w in weights:
            po = w * r['over_25'] + (1 - w) * o0
            pb = w * r['btts'] + (1 - w) * b0
            acc[w]['bo'] += (po - (1 if ao else 0)) ** 2
            acc[w]['bb'] += (pb - (1 if ab else 0)) ** 2
            acc[w]['ho'] += ((po > 0.5) == ao)
            acc[w]['hb'] += ((pb > 0.5) == ab)

        gd = r.get('goals_distribution') or {}
        if gd:
            def _i(k):
                return 7 if k == '7+' else int(k)
            mp = max(gd, key=gd.get)
            tg_n += 1
            tg_hit += (_i(mp) == min(h + a, 7))

    print('')
    print('=== 样本外结果 (%d 场, 失败 %d) ===' % (n, miss))
    print('  1X2 准确率 %.1f%% (多分类 Brier %.4f, 常数基线 0.6484)' % (ok1x2 / n * 100, b1x2 / n))
    print('  总进球最高档命中 %.1f%% (%d/%d) —— 8 档随机为 12.5%%' % (
        tg_hit / tg_n * 100, tg_hit, tg_n))
    print('')
    print('  收缩权重  大小球Brier  双进球Brier  大2.5命中  BTTS命中')
    for w in weights:
        v = acc[w]
        tag = '  ←现状' if w == 1.0 else ('  ←纯基准' if w == 0.0 else '')
        print('  %-9.1f %-12.4f %-12.4f %-11s %s%s' % (
            w, v['bo'] / n, v['bb'] / n,
            '%.1f%%' % (v['ho'] / n * 100), '%.1f%%' % (v['hb'] / n * 100), tag))


if __name__ == '__main__':
    main()
