"""复盘对比 v2: 用真实市场隐含方向(非edge方向)"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

all_matches = []

for date in ['08', '09', '10', '11']:
    try:
        preds = json.loads(open(f'data/output/predictions_2026-08-{date}.json', encoding='utf-8').read())
    except:
        continue
    try:
        results = json.loads(open(f'data/output/results_2026-08-{date}.json', encoding='utf-8').read())
    except:
        continue

    res_map = {}
    for r in results:
        key = (r['home_team'].lower().strip(), r['away_team'].lower().strip())
        res_map[key] = r

    for p in preds:
        h = p['home_team'].lower().strip()
        a = p['away_team'].lower().strip()
        r = res_map.get((h, a))
        if not r:
            for (rh, ra), rv in res_map.items():
                if (h[:8] in rh or rh[:8] in h) and (a[:8] in ra or ra[:8] in a):
                    r = rv
                    break
        if not r:
            continue

        m = p.get('model', p)
        mp_h = m.get('home_win', 0.33)
        mp_d = m.get('draw', 0.33)
        mp_a = m.get('away_win', 0.33)
        model_dir = ['H', 'D', 'A'][max(range(3), key=lambda i: [mp_h, mp_d, mp_a][i])]

        # Derive TRUE market-implied probs from model probs + edges
        v = p.get('value')
        if v and v.get('home_edge') is not None:
            # edge = model_prob - market_implied_prob
            # → market_implied_prob = model_prob - edge
            mkt_h = max(0.05, mp_h - v.get('home_edge', 0))
            mkt_d = max(0.05, mp_d - v.get('draw_edge', 0))
            mkt_a = max(0.05, mp_a - v.get('away_edge', 0))
            # Normalize
            total = mkt_h + mkt_d + mkt_a
            mkt_h /= total
            mkt_d /= total
            mkt_a /= total
            market_dir = ['H', 'D', 'A'][max(range(3), key=lambda i: [mkt_h, mkt_d, mkt_a][i])]
            market_probs = [mkt_h, mkt_d, mkt_a]
        else:
            market_dir = '?'
            market_probs = None

        hg = r['home_goals']
        ag = r['away_goals']
        if hg > ag:
            actual = 'H'
        elif hg == ag:
            actual = 'D'
        else:
            actual = 'A'

        elo_diff = p.get('elo_diff', 0)
        cold = p.get('cold_start') or m.get('cold_start', False)

        all_matches.append({
            'date': f'08-{date}',
            'home': p['home_team'][:20],
            'away': p['away_team'][:20],
            'model_dir': model_dir,
            'model_h': mp_h, 'model_d': mp_d, 'model_a': mp_a,
            'market_dir': market_dir,
            'market_h': mkt_h if market_probs else 0,
            'market_d': mkt_d if market_probs else 0,
            'market_a': mkt_a if market_probs else 0,
            'actual': actual,
            'elo_diff': elo_diff,
            'cold': cold,
            'hg': hg, 'ag': ag,
        })

market_avail = [m for m in all_matches if m['market_dir'] != '?']
total = len(all_matches)
cold_cnt = sum(1 for m in all_matches if m['cold'])

print(f'数据: {total}场 (有市场赔率{len(market_avail)}场, 冷启动{cold_cnt}场)')
print()

# Core metrics
model_ok = sum(1 for m in all_matches if m['model_dir'] == m['actual'])
market_ok = sum(1 for m in market_avail if m['market_dir'] == m['actual'])
print(f'模型方向准确率: {model_ok}/{total} = {model_ok/total*100:.1f}%')
print(f'市场隐含方向准确率: {market_ok}/{len(market_avail)} = {market_ok/len(market_avail)*100:.1f}%')
print()

# Known ELO vs Cold start
known = [m for m in all_matches if not m['cold']]
cold_m = [m for m in all_matches if m['cold']]
print(f'已知ELO: {len(known)}场, 模型准确率={sum(1 for m in known if m["model_dir"]==m["actual"])/len(known)*100:.1f}%')
print(f'冷启动: {len(cold_m)}场, 模型准确率={sum(1 for m in cold_m if m["model_dir"]==m["actual"])/len(cold_m)*100:.1f}%')
if market_avail:
    known_mkt = [m for m in market_avail if not m['cold']]
    cold_mkt = [m for m in market_avail if m['cold']]
    if known_mkt:
        print(f'市场(已知ELO): {sum(1 for m in known_mkt if m["market_dir"]==m["actual"])}/{len(known_mkt)} = {sum(1 for m in known_mkt if m["market_dir"]==m["actual"])/len(known_mkt)*100:.1f}%')
    if cold_mkt:
        print(f'市场(冷启动): {sum(1 for m in cold_mkt if m["market_dir"]==m["actual"])}/{len(cold_mkt)} = {sum(1 for m in cold_mkt if m["market_dir"]==m["actual"])/len(cold_mkt)*100:.1f}%')
print()

# Agreement analysis
agree = [m for m in market_avail if m['market_dir'] == m['model_dir']]
disagree = [m for m in market_avail if m['market_dir'] != m['model_dir']]

print('='*70)
print('方向一致 vs 冲突')
print('='*70)

if agree:
    correct = sum(1 for m in agree if m['model_dir'] == m['actual'])
    # When they agree, what fraction of the time are they right?
    print(f'[一致] {len(agree)}场 ({len(agree)/len(market_avail)*100:.0f}%)')
    print(f'  两者都对: {correct}场 ({correct/len(agree)*100:.0f}%)')
    # Show wrong ones
    wrong_agree = [m for m in agree if m['model_dir'] != m['actual']]
    if wrong_agree:
        print(f'  两者都错: {len(wrong_agree)}场')
        for m in wrong_agree:
            print(f'    {m["date"]} {m["home"]} vs {m["away"]} 都选{m["model_dir"]} 实际{m["actual"]}({m["hg"]}-{m["ag"]}) ELO差{m["elo_diff"]:+.0f}')

if disagree:
    market_right = sum(1 for m in disagree if m['market_dir'] == m['actual'])
    model_right = sum(1 for m in disagree if m['model_dir'] == m['actual'])
    neither_right = sum(1 for m in disagree if m['market_dir'] != m['actual'] and m['model_dir'] != m['actual'])
    print(f'\n[冲突] {len(disagree)}场 ({len(disagree)/len(market_avail)*100:.0f}%)')
    print(f'  市场对: {market_right}场')
    print(f'  模型对: {model_right}场')
    print(f'  都错: {neither_right}场')
    print(f'  冲突时跟模型: {model_right}/{len(disagree)} = {model_right/len(disagree)*100:.1f}%')
    print()

# Conflict details sorted by ELO diff
print('冲突详情 (按ELO差排序):')
for m in sorted(disagree, key=lambda x: abs(x['elo_diff']), reverse=True):
    mkt_win = '✓' if m['market_dir'] == m['actual'] else '✗'
    mdl_win = '✓' if m['model_dir'] == m['actual'] else '✗'
    cold_tag = ' [冷]' if m['cold'] else ''
    dir_cn = lambda d: {'H':'主','D':'平','A':'客'}.get(d,d)
    print(f'  ELO差{m["elo_diff"]:+4.0f} {m["date"]} {m["home"]} vs {m["away"]}{cold_tag}')
    print(f'    市场{dir_cn(m["market_dir"])}({mkt_win}) 模型{dir_cn(m["model_dir"])}({mdl_win}) 实际{dir_cn(m["actual"])}({m["hg"]}-{m["ag"]})')
    print(f'    市场: H={m["market_h"]:.1%} D={m["market_d"]:.1%} A={m["market_a"]:.1%}')
    print(f'    模型: H={m["model_h"]:.1%} D={m["model_d"]:.1%} A={m["model_a"]:.1%}')

print()
print('='*70)
print('策略模拟')
print('='*70)

# Pure strategies
print(f'保守派(纯跟市场): {market_ok}/{len(market_avail)} = {market_ok/len(market_avail)*100:.1f}%')
print(f'激进派(纯跟模型): {sum(1 for m in market_avail if m["model_dir"]==m["actual"])}/{len(market_avail)} = {sum(1 for m in market_avail if m["model_dir"]==m["actual"])/len(market_avail)*100:.1f}%')
print()

# Smart conservation: follow market, but switch to model when conflict + strong signals
for elo_thresh in [150, 200, 250]:
    ok = 0
    flips = 0
    for m in market_avail:
        if m['market_dir'] != m['model_dir'] and abs(m['elo_diff']) > elo_thresh and not m['cold']:
            bet = m['model_dir']
            flips += 1
        else:
            bet = m['market_dir']
        if bet == m['actual']:
            ok += 1
    print(f'混合(冲突+ELO>{elo_thresh}+非冷→跟模型): {ok}/{len(market_avail)} = {ok/len(market_avail)*100:.1f}% (翻盘{flips}场)')

# Model confidence threshold
for conf in [0.50, 0.55, 0.60]:
    ok = 0
    flips = 0
    for m in market_avail:
        if m['market_dir'] != m['model_dir'] and not m['cold']:
            mdl_conf = m['model_h'] if m['model_dir'] == 'H' else (m['model_d'] if m['model_dir'] == 'D' else m['model_a'])
            if mdl_conf > conf:
                bet = m['model_dir']
                flips += 1
            else:
                bet = m['market_dir']
        else:
            bet = m['market_dir']
        if bet == m['actual']:
            ok += 1
    print(f'混合(冲突+模型conf>{conf}+非冷→跟模型): {ok}/{len(market_avail)} = {ok/len(market_avail)*100:.1f}% (翻盘{flips}场)')

print()
print('='*70)
print('深层分析: 为什么错?')
print('='*70)

# Category analysis
both_wrong = [m for m in market_avail if m['market_dir'] != m['actual'] and m['model_dir'] != m['actual']]
draw_wrong = [m for m in both_wrong if m['actual'] == 'D']
reverse_wrong = [m for m in both_wrong if m['actual'] != 'D']

print(f'两者都错({len(both_wrong)}场):')
print(f'  实际是平局: {len(draw_wrong)}场 → 双方都猜不到平局')
for m in draw_wrong:
    print(f'    {m["date"]} {m["home"]} vs {m["away"]} 结果{m["hg"]}-{m["ag"]} 都选{m["model_dir"]}')
print(f'  实际方向反转: {len(reverse_wrong)}场 → 强弱判断反了')
for m in reverse_wrong:
    print(f'    {m["date"]} {m["home"]} vs {m["away"]} 都选{m["model_dir"]} 实际{m["actual"]}({m["hg"]}-{m["ag"]})')

print()
print('='*70)
print('过滤策略模拟')
print('='*70)

# Filter: skip high-draw-probability matches
for draw_thresh in [0.24, 0.26, 0.28]:
    ok = 0
    skipped = 0
    total_bet = 0
    for m in market_avail:
        if m['model_d'] > draw_thresh:
            skipped += 1
            continue
        total_bet += 1
        if m['market_dir'] == m['actual']:
            ok += 1
    if total_bet > 0:
        print(f'跳过模型平局>{draw_thresh:.0%}: {ok}/{total_bet} = {ok/total_bet*100:.1f}% (跳过{skipped}场)')

# Filter: only bet when model confident AND market agrees
for conf in [0.50, 0.55, 0.60]:
    ok = 0
    skipped = 0
    total_bet = 0
    for m in market_avail:
        mdl_conf = m['model_h'] if m['model_dir'] == 'H' else (m['model_d'] if m['model_dir'] == 'D' else m['model_a'])
        if mdl_conf < conf:
            skipped += 1
            continue
        total_bet += 1
        if m['market_dir'] == m['actual']:
            ok += 1
    if total_bet > 0:
        print(f'模型conf>{conf:.0%}: {ok}/{total_bet} = {ok/total_bet*100:.1f}% (跳过{skipped}场)')

# Best filter: skip draw-prone AND low confidence
for conf in [0.50, 0.55]:
    for draw_thresh in [0.24, 0.26]:
        ok = 0
        skipped = 0
        total_bet = 0
        for m in market_avail:
            mdl_conf = m['model_h'] if m['model_dir'] == 'H' else (m['model_d'] if m['model_dir'] == 'D' else m['model_a'])
            if m['model_d'] > draw_thresh or mdl_conf < conf:
                skipped += 1
                continue
            total_bet += 1
            if m['market_dir'] == m['actual']:
                ok += 1
        if total_bet >= 5:
            print(f'跳过平局>{draw_thresh:.0%}且conf<{conf:.0%}: {ok}/{total_bet} = {ok/total_bet*100:.1f}% (跳过{skipped}场)')

# Filter: bet only when ELO diff is clear
for elo_min in [50, 100, 150]:
    ok = 0
    skipped = 0
    total_bet = 0
    for m in market_avail:
        if abs(m['elo_diff']) < elo_min:
            skipped += 1
            continue
        total_bet += 1
        if m['market_dir'] == m['actual']:
            ok += 1
    if total_bet >= 5:
        print(f'仅|ELO差|>{elo_min}: {ok}/{total_bet} = {ok/total_bet*100:.1f}% (跳过{skipped}场)')

print()
print('='*70)
print('最终建议')
print('='*70)

# Compute best strategy
# Conservative base: follow market, skip draws
ok_skip_draw = 0
total_bet_skip_draw = 0
for m in market_avail:
    if m['model_d'] > 0.25:
        continue  # skip draw-prone matches
    total_bet_skip_draw += 1
    if m['market_dir'] == m['actual']:
        ok_skip_draw += 1

# Market + skip draws + skip cold
ok_skip_draw_cold = 0
total_bet_skip_draw_cold = 0
for m in market_avail:
    if m['model_d'] > 0.25 or m['cold']:
        continue
    total_bet_skip_draw_cold += 1
    if m['market_dir'] == m['actual']:
        ok_skip_draw_cold += 1

# Market + skip draws + skip cold + skip low ELO
ok_best = 0
total_bet_best = 0
for m in market_avail:
    if m['model_d'] > 0.25 or m['cold'] or abs(m['elo_diff']) < 50:
        continue
    total_bet_best += 1
    if m['market_dir'] == m['actual']:
        ok_best += 1

print(f'纯跟市场:                          {market_ok}/{len(market_avail)} = {market_ok/len(market_avail)*100:.1f}%')
print(f'跟市场+跳过平局>25%:                {ok_skip_draw}/{total_bet_skip_draw} = {ok_skip_draw/total_bet_skip_draw*100:.1f}%')
print(f'跟市场+跳过平局>25%+跳过冷启动:      {ok_skip_draw_cold}/{total_bet_skip_draw_cold} = {ok_skip_draw_cold/total_bet_skip_draw_cold*100:.1f}%')
print(f'跟市场+跳过平局+跳过冷启动+|ELO|>50: {ok_best}/{total_bet_best} = {ok_best/total_bet_best*100:.1f}%')
print()
print(f'样本量警告: 仅{len(market_avail)}场，所有结论需更多数据验证')
