import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
d = json.load(open('data/output/predictions_2026-08-16.json', encoding='utf-8'))
out = []
for p in d:
    out.append(p['home_team'] + ' vs ' + p['away_team'] + ' | std: ' + json.dumps(p.get('standings'), ensure_ascii=False))
s = json.load(open('data/state/standings.json', encoding='utf-8'))
pd_keys = sorted(s.get('PD', {}).keys())
out.append('PD keys sample: ' + ', '.join(pd_keys[:8]))
out.append('PD keys with villarreal: ' + str([k for k in pd_keys if 'villarreal' in k]))
open('_std_dbg.txt', 'w', encoding='utf-8').write(chr(10).join(out))