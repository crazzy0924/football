# -*- coding: utf-8 -*-
"""回归检查: 预测的「首选比分」会不会跟「胜平负方向」打架?

2026-09-11 立。背景: 联合约束(_joint_top_scores)原先只约束让球盘+大小球, 没管
胜平负方向, 导致 26% 的场次出现"众数 1-1 但方向主胜"的假矛盾, 被打上
「结论不可用」。补上方向硬约束后本检查应恒为 0。

用法:
    python tools/check_no_direction_conflict.py
"""
import glob
import importlib.util
import json
import os
import sys

sys.path.insert(0, '.')
# pipeline.py 与 pipeline/ 包同名, 必须按文件路径加载脚本本体
_spec = importlib.util.spec_from_file_location('pipeline_cli', 'pipeline.py')
_cli = importlib.util.module_from_spec(_spec)
sys.modules['pipeline_cli'] = _cli
_spec.loader.exec_module(_cli)

LAB = {'H': '主胜', 'D': '平局', 'A': '客胜'}


def main():
    n = conflict = jt_none = 0
    bad = []
    for fp in sorted(glob.glob('data/output/predictions_????-??-??.json')):
        for p in json.load(open(fp, encoding='utf-8')):
            model = p.get('model') or {}
            if not any(model.get(k) for k in ('home_win', 'draw', 'away_win')):
                continue
            n += 1
            jt = _cli._joint_top_scores(model, p.get('ah_handicap'), p.get('ou_value'), p.get('bayesian'))
            if jt is None:
                jt_none += 1
            fl = _cli._consistency_flags(model, jt, p.get('bayesian'))
            if fl.get('direction_score_conflict'):
                conflict += 1
                if len(bad) < 10:
                    bad.append('%s %s vs %s' % (os.path.basename(fp)[12:22], p['home_team'], p['away_team']))

    print('检查 %d 场预测' % n)
    print('  方向-比分冲突: %d' % conflict)
    print('  joint_top_scores 为空: %d' % jt_none)
    if conflict:
        print('')
        print('[FAIL] 存在方向-比分冲突:')
        for s in bad:
            print('   ' + s)
        raise SystemExit(1)
    print('')
    print('[OK] 比分与方向全部自洽')


if __name__ == '__main__':
    main()
