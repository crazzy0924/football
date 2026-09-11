# -*- coding: utf-8 -*-
"""建立跨联赛参数索引: 每支球队在各联赛的攻防参数 + 样本量。

用途: 欧冠球队样本普遍只有 6~20 场, 单靠欧冠数据估不准攻防强度。
     用它在所属五大联赛里估好的参数做收缩(shrinkage)兜底。
产物: data/state/cross_league_params.json
"""
import csv
import glob
import io
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data', 'historical_odds')
MODELS = os.path.join(ROOT, 'data', 'state', 'models')
OUT = os.path.join(ROOT, 'data', 'state', 'cross_league_params.json')

# 联赛代码 → historical_odds 里的文件名前缀
CSV_CODE = {
    'PL': 'E0', 'PD': 'SP1', 'BL1': 'D1', 'SA': 'I1', 'FL1': 'F1',
    'UCL': 'CL', 'ELC': 'E1', 'PD2': 'SP2', 'BL2': 'D2', 'FL2': 'F2', 'SB': 'I2',
}


def team_match_counts(league: str) -> Counter:
    """该联赛历史 CSV 里每支球队出现的场次 (队名归一到我们的规范名)。

    2026-09-11: CSV 里是 football-data 的全称(FC Bayern München), 模型里是简称
    (Bayern Munich) —— 不归一的话统计出来全是 0。
    """
    code = CSV_CODE.get(league)
    if not code:
        return Counter()
    try:
        from pipeline.team_names import canonical_of
    except Exception:
        canonical_of = lambda x: None
    c: Counter = Counter()
    for fp in glob.glob(os.path.join(HIST, code + '_*')):
        if not fp.lower().endswith(('.csv', '.txt')):
            continue
        try:
            with io.open(fp, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    h = (row.get('HomeTeam') or row.get('Home') or '').strip()
                    a = (row.get('AwayTeam') or row.get('Away') or '').strip()
                    if h:
                        c[canonical_of(h) or h] += 1
                    if a:
                        c[canonical_of(a) or a] += 1
        except Exception:
            continue
    return c


def main():
    # 1) 各联赛模型里的球队参数
    per_league: dict[str, dict] = {}
    for lg in sorted(os.listdir(MODELS)):
        fp = os.path.join(MODELS, lg, 'team_params.json')
        if not os.path.isfile(fp):
            continue
        try:
            per_league[lg] = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue

    # 2) 每队在每个联赛的样本量
    counts = {lg: team_match_counts(lg) for lg in per_league}

    # 3) 汇总: 规范名 → [{league, attack, defense, n}]
    # 2026-09-11: 必须用规范名做键。模型里叫 "Real Madrid CF", 预测里叫 "Real Madrid",
    # 用原名做键会导致回测时一半球队查不到。
    try:
        from pipeline.team_names import canonical_of
    except Exception:
        canonical_of = lambda x: None
    idx: dict[str, list] = defaultdict(list)
    for lg, teams in per_league.items():
        cnt = counts.get(lg) or Counter()
        for name, p in teams.items():
            if not isinstance(p, dict):
                continue
            idx[canonical_of(name) or name].append({
                'league': lg,
                'attack': p.get('attack'),
                'defense': p.get('defense'),
                # CSV 里名字与模型名不一定一致, 命不中就记 0 (由构建端保守处理)
                'n': int(cnt.get(name, 0)),
            })

    # 4) 只保留"在多个联赛出现过"或"在欧冠出现过"的, 减小体积
    out = {k: v for k, v in idx.items() if len(v) > 1 or any(x['league'] == 'UCL' for x in v)}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # 报告
    multi = sum(1 for v in out.values() if len(v) > 1)
    ucl = sum(1 for v in out.values() if any(x['league'] == 'UCL' for x in v))
    ucl_thin = 0
    for k, v in out.items():
        u = [x for x in v if x['league'] == 'UCL']
        if u and (u[0]['n'] or 0) < 20:
            ucl_thin += 1
    print('索引球队: %d 支 (跨联赛 %d, 含欧冠 %d)' % (len(out), multi, ucl))
    print('欧冠样本 <20 场: %d 支' % ucl_thin)
    print('')
    print('样例 (欧冠 / 五大 双份参数):')
    shown = 0
    for k, v in sorted(out.items()):
        u = [x for x in v if x['league'] == 'UCL']
        d = [x for x in v if x['league'] in ('PL', 'PD', 'BL1', 'SA', 'FL1')]
        if u and d and shown < 10:
            shown += 1
            print('  %-26s 欧冠 n=%-3d att=%-6s def=%-6s | %s n=%-3d att=%-6s def=%s' % (
                k, u[0]['n'], u[0]['attack'], u[0]['defense'],
                d[0]['league'], d[0]['n'], d[0]['attack'], d[0]['defense']))
    print('')
    print('已保存 → %s' % OUT)


if __name__ == '__main__':
    main()
