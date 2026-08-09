"""初盘 vs 临盘 下注变动对比"""
import json, subprocess

# Get opening bets from git
r = subprocess.run(['git', 'show', '8e38b14:data/output/pinnacle_bets_20260809.json'],
                   capture_output=True, text=True, encoding='utf-8')
opening = json.loads(r.stdout)

# Get closing bets (current file)
closing = json.load(open('data/output/pinnacle_bets_20260809.json', 'r', encoding='utf-8'))

open_map = {(b['home'], b['away']): b for b in opening['bets']}
close_map = {(b['home'], b['away']): b for b in closing['bets']}
all_keys = sorted(set(list(open_map.keys()) + list(close_map.keys())))

print('=' * 100)
print('  初盘 vs 临盘 下注变动')
print('=' * 100)

stats = {'same': 0, 'odds_changed': 0, 'dim_changed': 0, 'kicked': 0, 'new': 0}
dim_cn = {'胜平负': '1X2', '亚洲盘': 'AH', '大小球': 'OU'}

for key in all_keys:
    h, a = key
    o = open_map.get(key)
    c = close_map.get(key)

    if o and c:
        if o['dim'] == c['dim'] and o['direction'] == c['direction']:
            if abs(o['odds'] - c['odds']) > 0.1:
                print(f'\n  [{h} vs {a}]')
                print(f'    初: {o["dim"]} {o["direction"]} @{o["odds"]:.2f} K={o["kelly"]:.0%} Y{o["stake"]}')
                print(f'    临: {c["dim"]} {c["direction"]} @{c["odds"]:.2f} K={c["kelly"]:.0%} Y{c["stake"]}')
                print(f'    -> 赔率变动 {c["odds"]-o["odds"]:+.2f}')
                stats['odds_changed'] += 1
            else:
                stats['same'] += 1
        else:
            print(f'\n  [DIR CHG] {h} vs {a}')
            print(f'    初: {o["dim"]} {o["direction"]} @{o["odds"]:.2f} K={o["kelly"]:.0%} Y{o["stake"]}')
            print(f'    临: {c["dim"]} {c["direction"]} @{c["odds"]:.2f} K={c["kelly"]:.0%} Y{c["stake"]}')
            tag = '!!!' if (o['dim'] != c['dim']) else ''
            print(f'    -> {tag} {"维度改变" if o["dim"] != c["dim"] else "方向改变"}')
            stats['dim_changed'] += 1
    elif o and not c:
        print(f'\n  [KICKED] {h} vs {a} — 初盘 {o["dim"]} {o["direction"]}')
        stats['kicked'] += 1
    elif c and not o:
        print(f'\n  [NEW] {h} vs {a} — 临盘 {c["dim"]} {c["direction"]}')
        stats['new'] += 1

print(f'\n{"=" * 100}')
print(f'  不变: {stats["same"]} | 赔率变动: {stats["odds_changed"]} | 方向改变: {stats["dim_changed"]} | 已开踢: {stats["kicked"]} | 新增: {stats["new"]}')
print(f'  初盘: {opening["total"]}Y {len(opening["bets"])}注 | 临盘: {closing["total"]}Y {len(closing["bets"])}注')
print(f'{"=" * 100}')
