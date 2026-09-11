# -*- coding: utf-8 -*-
"""生成数据驱动的联赛自画像 → data/state/league_profiles.json

为什么要它:
  models/league_profiles.py 里的 LEAGUE_PROFILES 是**手写死的**数值, 而且:
    - 数值陈旧 (意甲主场优势写 0.30, 实测只有 0.158, 高估近一倍)
    - **没有 UCL 条目** → get_profile("UCL") 落到通用默认, 与"欧冠有欧冠的特点"冲突
    - over_25_rate / btts_rate 是手写的, 从没进过模型
  这个脚本从历史 CSV 直接算, 每个联赛一份, 谁也不用套谁的模板。

用法:
    python tools/build_league_profiles.py
"""
import csv
import glob
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data', 'historical_odds')
OUT = os.path.join(ROOT, 'data', 'state', 'league_profiles.json')

CSV_CODE = {
    'PL': 'E0', 'PD': 'SP1', 'BL1': 'D1', 'SA': 'I1', 'FL1': 'F1',
    'UCL': 'CL', 'ELC': 'E1', 'PD2': 'SP2', 'BL2': 'D2', 'FL2': 'F2', 'SB': 'I2',
}
STYLE = {
    'PL': 'high_intensity', 'PD': 'technical', 'BL1': 'high_scoring',
    'SA': 'defensive', 'FL1': 'physical', 'UCL': 'elite_knockout',
}


def _f(v):
    try:
        return float(v)
    except Exception:
        return None


def scan(league: str) -> dict | None:
    code = CSV_CODE.get(league)
    if not code:
        return None
    n = 0
    hg = ag = 0
    hw = dr = aw_ = 0
    over25 = btts = 0
    corners = corners_home = 0
    n_corner = 0
    per_season: dict = defaultdict(lambda: {'n': 0, 'hg': 0, 'ag': 0, 'hw': 0, 'd': 0, 'aw': 0})
    for fp in sorted(glob.glob(os.path.join(HIST, code + '_*'))):
        if not fp.lower().endswith(('.csv', '.txt')):
            continue
        season = os.path.basename(fp).split('_')[-1].rsplit('.', 1)[0]
        try:
            with io.open(fp, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    H, A = _f(row.get('FTHG')), _f(row.get('FTAG'))
                    r = (row.get('FTR') or '').strip()
                    if H is None or A is None:
                        continue
                    n += 1
                    hg += H
                    ag += A
                    if r == 'H':
                        hw += 1
                    elif r == 'D':
                        dr += 1
                    elif r == 'A':
                        aw_ += 1
                    if H + A > 2.5:
                        over25 += 1
                    if H > 0 and A > 0:
                        btts += 1
                    hc, ac = _f(row.get('HC')), _f(row.get('AC'))
                    if hc is not None and ac is not None:
                        corners += hc + ac
                        corners_home += hc
                        n_corner += 1
                    s = per_season[season]
                    s['n'] += 1
                    s['hg'] += H
                    s['ag'] += A
                    if r == 'H':
                        s['hw'] += 1
                    elif r == 'D':
                        s['d'] += 1
                    else:
                        s['aw'] += 1
        except Exception:
            continue
    if n < 10:
        return None
    home_adv = (hg / ag - 1) if ag > 0 else 0.30
    multi = []
    for s, v in sorted(per_season.items()):
        if v['n'] < 10:
            continue
        multi.append({
            'season': s, 'n': v['n'],
            'home_win': round(v['hw'] / v['n'], 4),
            'draw': round(v['d'] / v['n'], 4),
            'away_win': round(v['aw'] / v['n'], 4),
            'goals': round((v['hg'] + v['ag']) / v['n'], 2),
        })
    return {
        'code': league, 'matches': n, 'seasons': len(multi),
        'avg_home_goals': round(hg / n, 3),
        'avg_away_goals': round(ag / n, 3),
        'avg_total_goals': round((hg + ag) / n, 3),
        'home_win_rate': round(hw / n, 4),
        'draw_rate': round(dr / n, 4),
        'away_win_rate': round(aw_ / n, 4),
        'home_goal_boost': round(home_adv, 4),
        'over_25_rate': round(over25 / n, 4),
        'btts_rate': round(btts / n, 4),
        'avg_corners': round(corners / n_corner, 2) if n_corner else None,
        'corner_home_share': round(corners_home / corners, 4) if corners else None,
        'style': STYLE.get(league, ''),
        'multi_season': multi,
    }


def main():
    out = {}
    print('%-6s %-8s %-8s %-8s %-8s %-8s %-8s %s' % (
        '联赛', '场次', '总进球', '主胜率', '平局率', '主场优势', '大2.5', 'BTTS'))
    for lg in ('PL', 'PD', 'BL1', 'SA', 'FL1', 'UCL', 'ELC', 'PD2', 'BL2', 'FL2', 'SB'):
        p = scan(lg)
        if not p:
            print('%-6s (数据不足)' % lg)
            continue
        out[lg] = p
        print('%-6s %-8d %-8.2f %-8.3f %-8.3f %-8.3f %-8.3f %.3f' % (
            lg, p['matches'], p['avg_total_goals'], p['home_win_rate'],
            p['draw_rate'], p['home_goal_boost'], p['over_25_rate'], p['btts_rate']))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('')
    print('已保存 %d 个联赛 → %s' % (len(out), OUT))


if __name__ == '__main__':
    main()
