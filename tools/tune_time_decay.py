# -*- coding: utf-8 -*-
"""时间衰减系数 λ 的样本外网格搜索 (Dixon-Coles 近因加权)。

做法: 按赛季滚动 —— 用"测试赛季开始前"的全部历史训练, 在该赛季上测试。
      每个 λ 在同一批切分上重拟一次, 比 Brier / LogLoss / 准确率。
参考线: 同批测试场次的"市场去水概率"Brier —— 模型的任务是与市场对齐, 不是跑赢它。
       (见 CLAUDE.md 第九节: 亚盘 ROI 恒定 -2.2% ≈ Pinnacle 抽水 → 模型 ≡ 市场)

用法:
    python tools/tune_time_decay.py
    python tools/tune_time_decay.py --seasons 3 --grid 0,0.002,0.005,0.01
"""
import argparse, io, sys, time
sys.path.insert(0, '.')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pipeline.data_loader import load_all_csvs
from models.dixon_coles import DixonColesModel

KEEP = {'PL', 'PD', 'BL1', 'SA', 'FL1', 'UCL'}


def devig(oh, od, oa):
    raw = [1.0 / oh, 1.0 / od, 1.0 / oa]
    s = sum(raw)
    return [x / s for x in raw]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, default=2, help='用最后 N 个赛季做测试 (默认2)')
    ap.add_argument('--grid', default='0,0.001,0.002,0.003,0.005,0.008',
                    help='λ 网格, 逗号分隔')
    ap.add_argument('--league', default='',
                    help='只测这些联赛, 逗号分隔 (默认六项全测)。用于看分联赛异质性')
    ap.add_argument('--paired', type=float, default=None,
                    help='配对检验: 在完全相同的测试场上比 λ=0 与给定 λ 的逐场 Brier 差')
    a = ap.parse_args()
    grid = [float(x) for x in a.grid.split(',') if x.strip()]
    keep = {x.strip().upper() for x in a.league.split(',') if x.strip()} or KEEP

    ms = [m for m in load_all_csvs()
          if m['league_code'] in keep and m.get('date')]
    ms.sort(key=lambda m: m['date'])
    seasons = sorted({m['season'] for m in ms})
    test_seasons = seasons[-a.seasons:]
    print('六项赛事 %d 场, 赛季 %s' % (len(ms), ' '.join(seasons)))
    print('测试赛季: %s' % ' '.join(test_seasons))

    splits = []
    for s in test_seasons:
        te = [m for m in ms if m['season'] == s]
        if not te:
            continue
        start = min(m['date'] for m in te)
        tr = [m for m in ms if m['date'] < start]
        splits.append((s, start, tr, te))
        print('  %s: 训练 %d 场 (< %s) / 测试 %d 场' % (s, len(tr), start, len(te)))

    # ── 配对检验模式 ──
    # 单看 Brier 绝对值, 组间方差远大于真实效应, 永远测不出显著。
    # 改成"同一批比赛上两个模型的逐场 Brier 差", 方差被比赛难度共同因子消掉,
    # 才是判断"到底有没有改善"的正确口径。
    if a.paired is not None:
        import math
        lam1 = a.paired
        D, nbetter, ntot = [], 0, 0
        per_lg: dict = {}
        for s, start, tr, te in splits:
            d0 = DixonColesModel(time_decay=0.0)
            d1 = DixonColesModel(time_decay=lam1)
            d0.fit_mle(tr)
            d1.fit_mle(tr)
            for m in te:
                try:
                    r0 = d0.predict(m['home_team'], m['away_team'], m['league_code'])
                    r1 = d1.predict(m['home_team'], m['away_team'], m['league_code'])
                except Exception:
                    continue
                if not r0 or not r1 or r0.get('home_win') is None or r1.get('home_win') is None:
                    continue
                h, gg = m['home_goals'], m['away_goals']
                k = 0 if h > gg else (1 if h == gg else 2)
                o = [0.0, 0.0, 0.0]
                o[k] = 1.0
                b0 = sum(([r0['home_win'], r0['draw'], r0['away_win']][i] - o[i]) ** 2 for i in range(3))
                b1 = sum(([r1['home_win'], r1['draw'], r1['away_win']][i] - o[i]) ** 2 for i in range(3))
                D.append(b1 - b0)
                nbetter += (b1 < b0)
                ntot += 1
                per_lg.setdefault(m['league_code'], []).append(b1 - b0)
        if D:
            n = len(D)
            mu = sum(D) / n
            sd = (sum((x - mu) ** 2 for x in D) / (n - 1)) ** 0.5 if n > 1 else 0.0
            se = sd / math.sqrt(n) if n else 0.0
            print()
            print('配对检验 λ=%.4f vs λ=0  (n=%d)' % (lam1, n))
            print('  平均逐场 Brier 差 = %+.5f  (负=λ>0 更好)   标准误 %.5f   t = %s' % (
                mu, se, ('%.2f' % (mu / se)) if se else '—'))
            print('  95%% 置信区间 [%+.5f, %+.5f]' % (mu - 1.96 * se, mu + 1.96 * se))
            print('  λ>0 逐场更优的比例 = %.1f%%' % (nbetter / n * 100))
            print('  分联赛:')
            for lg in sorted(per_lg):
                dd = per_lg[lg]
                if len(dd) < 30:
                    continue
                mm = sum(dd) / len(dd)
                ss = (sum((x - mm) ** 2 for x in dd) / (len(dd) - 1)) ** 0.5 / math.sqrt(len(dd))
                print('    %-5s n=%-5d 差=%+.5f  se=%.5f  t=%-6s %s' % (
                    lg, len(dd), mm, ss, ('%.2f' % (mm / ss)) if ss else '—',
                    '显著' if ss and abs(mm / ss) > 2 else '不显著'))
        return

    print()
    hdr = '%-9s %-8s %-9s %-9s %-8s %-9s' % ('λ', '测试场次', 'Brier', 'LogLoss', '准确率', '市场Brier')
    print(hdr)
    print('-' * len(hdr))
    best = None
    for lam in grid:
        t0 = time.time()
        nb = nl = nm = 0.0
        n = 0
        acc = 0
        mk = 0
        for s, start, tr, te in splits:
            dc = DixonColesModel(time_decay=lam)
            try:
                dc.fit_mle(tr)
            except Exception as e:
                print('  %s 拟合失败: %s' % (s, str(e)[:60]))
                continue
            for m in te:
                try:
                    r = dc.predict(m['home_team'], m['away_team'], m['league_code'])
                except Exception:
                    continue
                if not r or r.get('home_win') is None:
                    continue
                p = [r['home_win'], r['draw'], r['away_win']]
                h, gg = m['home_goals'], m['away_goals']
                k = 0 if h > gg else (1 if h == gg else 2)
                o = [0.0, 0.0, 0.0]
                o[k] = 1.0
                nb += sum((p[i] - o[i]) ** 2 for i in range(3))
                nl += -__import__('math').log(max(p[k], 1e-12))
                acc += (int(p.index(max(p))) == k)
                n += 1
                po = (m.get('odds') or {}).get('pinnacle') or {}
                if po.get('home') and po.get('draw') and po.get('away'):
                    f = devig(po['home'], po['draw'], po['away'])
                    nm += sum((f[i] - o[i]) ** 2 for i in range(3))
                    mk += 1
        if not n:
            continue
        b = nb / n
        row = '%-9.4f %-8d %-9.4f %-9.4f %-8.1f%% %-9s' % (
            lam, n, b, nl / n, acc / n * 100,
            ('%.4f' % (nm / mk)) if mk else '—')
        print(row + '   (%.0fs)' % (time.time() - t0))
        if best is None or b < best[1]:
            best = (lam, b)
    if best:
        print()
        print('样本外 Brier 最优: λ = %.4f (Brier %.4f)' % best)


if __name__ == '__main__':
    main()
