import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from pipeline.data_loader import load_all_matches
from datetime import datetime, timedelta
from collections import defaultdict
ms = load_all_matches()
# 每队最近比赛日期 (按时间序推进)
last_date = {}
out = []
rest_diff_buckets = defaultdict(lambda: [0, 0, 0, 0])  # n, home_wins, draws, goals_diff
total = 0
for m in ms:
    d = m['date']
    try:
        dt = datetime.strptime(d, '%Y-%m-%d')
    except (ValueError, TypeError):
        continue
    h, a = m['home_team'], m['away_team']
    h_rest = (dt - last_date[h]).days if h in last_date else 99
    a_rest = (dt - last_date[a]).days if a in last_date else 99
    if h_rest >= 0 and a_rest >= 0 and h_rest <= 30 and a_rest <= 30:
        diff = h_rest - a_rest
        # 分桶: <=-3, -2, -1, 0, 1, 2, >=3
        b = max(-3, min(3, diff))
        st = rest_diff_buckets[b]
        st[0] += 1
        if m['result'] == 'H': st[1] += 1
        elif m['result'] == 'D': st[2] += 1
        st[3] += m['home_goals'] - m['away_goals']
        total += 1
    last_date[h] = dt
    last_date[a] = dt
out.append('有效场次(两队休息<=30天): ' + str(total))
out.append('休息差(主-客) | 场次 | 主胜率 | 平率 | 平均净胜球')
for b in range(-3, 4):
    st = rest_diff_buckets[b]
    if st[0] == 0: continue
    out.append(f'{b:+d} | {st[0]:>6} | {st[1]/st[0]:.1%} | {st[2]/st[0]:.1%} | {st[3]/st[0]:+.3f}')
open('_rest_analysis.txt', 'w', encoding='utf-8').write(chr(10).join(out))
print('done')