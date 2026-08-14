"""三线合并全维度预测 — 1X2 + 亚洲盘 + 大小球 — Shin去水 + Kelly下注

用法:
  python run_pinnacle_bets.py                              # 默认读取 data/pinnacle_odds_DATE.json
  python run_pinnacle_bets.py --odds data/pinnacle_early_2026-08-09.json
  python run_pinnacle_bets.py --date 2026-08-09 --window early  # 等价于上面
"""
import io, json, math, sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# -- Config --
LEAGUE_CN = {'J1':'日职联','J2':'日乙','DED':'荷甲','BL2':'德乙',
             'SWE':'瑞典超','FIN':'芬超','NOR':'挪超','PPL':'葡超','BSA':'巴甲'}
BANKROLL = 10000; KF = 0.25
DIRMAP = {'home':'主胜','draw':'平局','away':'客胜'}

# -- Shin devigging --
def shin_1x2(h_odd, d_odd, a_odd, max_iter=150):
    odds = [1/h_odd, 1/d_odd, 1/a_odd]
    z0 = sum(odds); margin = z0 - 1.0
    if margin <= 0: return [o/z0 for o in odds], 0
    c = min(0.5, margin * 0.8)
    for _ in range(max_iter):
        denom = sum(math.sqrt(c + (1-c)*o**2) for o in odds)
        p = [math.sqrt(c + (1-c)*o**2)/denom for o in odds]
        cn = c * sum((1-x)**2 for x in p) / (3 - sum(x**2 for x in p))
        if abs(cn-c) < 1e-7: break
        c = cn
    return p, round(c, 6)

def shin_binary(price_a, price_b):
    p, c = shin_1x2(price_a, price_b, 999.0)
    return p[:2], c

# -- 比分分布工具 --
def handicap_probs(score_dist, goal_line):
    hc = ps = ac = 0.0
    for score, prob in score_dist.items():
        hg, ag = map(int, score.split('-'))
        adj = hg - ag + goal_line
        if adj > 0: hc += prob
        elif adj == 0: ps += prob
        else: ac += prob
    return {'home': hc, 'push': ps, 'away': ac}

def totals_probs(score_dist):
    dist = {}
    for score, prob in score_dist.items():
        hg, ag = map(int, score.split('-'))
        tg = hg + ag
        dist[tg] = dist.get(tg, 0) + prob
    over_25 = sum(p for g, p in dist.items() if g >= 3)
    over_35 = sum(p for g, p in dist.items() if g >= 4)
    return {'over_2_5': over_25, 'over_3_5': over_35, 'exp_goals': sum(g*p for g,p in dist.items())}

# -- 体彩/平博 → 规范英文队名映射 --
PINNACLE_NAME_MAP = {
    # J1
    'Tokyo Verdy': 'Tokyo Verdy', 'Kawasaki Frontale': 'Kawasaki Frontale',
    'V-Varen Nagasaki': 'V-Varen Nagasaki', 'Kyoto Purple Sanga': 'Kyoto Sanga',
    # DED
    'Sparta Rotterdam': 'Sparta Rotterdam', 'Feyenoord': 'Feyenoord',
    'FC Zwolle': 'Zwolle', 'Ajax': 'Ajax',
    'Groningen': 'Groningen', 'FC Utrecht': 'Utrecht',
    'Heerenveen': 'Heerenveen', 'FC Twente Enschede': 'Twente',
    # BL2
    '1. FC Nürnberg': 'Nurnberg', 'Dynamo Dresden': 'Dresden',
    'FC Energie Cottbus': 'Cottbus', 'Hannover 96': 'Hannover',
    'FC St. Pauli': 'St Pauli', 'Greuther Fürth': 'Greuther Furth',
    # SWE
    'Hammarby IF': 'Hammarby', 'BK Hacken': 'Hacken',
    'Malmo FF': 'Malmo', 'Degerfors IF': 'Degerfors',
    'Halmstads BK': 'Halmstads', 'GAIS': 'GAIS',
    'IFK Goteborg': 'IFK Goteborg', 'Kalmar FF': 'Kalmar',
    # FIN
    'KuPS Kuopio': 'KuPS', 'TPS Turku': 'TPS',
    'FC Inter Turku': 'Inter Turku', 'FC Lahti': 'Lahti',
    'Ilves Tampere': 'Ilves', 'IFK Mariehamn': 'Mariehamn',
    'AC Oulu': 'AC Oulu', 'HJK Helsinki': 'HJK Helsinki',
    # NOR
    'Lillestrom': 'Lillestrom', 'Rosenborg': 'Rosenborg',
    'HamKam': 'HamKam', 'Aalesund': 'Aalesund',
    'Kristiansund BK': 'Kristiansund', 'Molde': 'Molde',
    # PPL
    'FC Porto': 'Porto', 'Alverca': 'Alverca',
    'Benfica': 'Benfica', 'Académico de Viseu': 'Viseu',
    'Moreirense FC': 'Moreirense', 'Braga': 'Braga',
    'Gil Vicente': 'Gil Vicente', 'Rio Ave FC': 'Rio Ave',
    # BSA
    'Cruzeiro': 'Cruzeiro', 'Mirassol': 'Mirassol',
    'Bahia': 'Bahia', 'Vasco da Gama': 'Vasco',
    'Palmeiras': 'Palmeiras', 'Internacional': 'Internacional',
    'Santos': 'Santos', 'Atletico Paranaense': 'Athletico-PR',
    'Bragantino-SP': 'Bragantino', 'Corinthians': 'Corinthians',
    'Flamengo': 'Flamengo', 'Vitoria': 'Vitoria Guimaraes',
}

# -- Load data --
# 解析命令行参数
odds_file = None
date_str = None
time_window = None
for i, arg in enumerate(sys.argv):
    if arg == '--odds' and i+1 < len(sys.argv):
        odds_file = sys.argv[i+1]
    elif arg == '--date' and i+1 < len(sys.argv):
        date_str = sys.argv[i+1]
    elif arg == '--window' and i+1 < len(sys.argv):
        time_window = sys.argv[i+1]

if date_str is None:
    from datetime import datetime, timezone, timedelta
    bj = timezone(timedelta(hours=8))
    date_str = datetime.now(bj).strftime('%Y-%m-%d')

if odds_file is None:
    if time_window:
        odds_file = f'data/pinnacle_{time_window}_{date_str}.json'
    else:
        odds_file = f'data/pinnacle_odds_{date_str}.json'
        if not Path(odds_file).exists():
            odds_file = f'data/pinnacle_odds_{date_str.replace("-","")}.json'

pred_path = f'data/output/predictions_{date_str}.json'
today_match_file = 'data/today_matches_v3.json' if Path('data/today_matches_v3.json').exists() else f'data/today_matches_{date_str.replace("-","")}.json'
with open(today_match_file, 'r', encoding='utf-8') as f:
    matches = json.load(f)

# 构建英→中队名映射(先精确后子串)
en_to_cn = {}
for m in matches:
    h_full = m['home_team']; a_full = m['away_team']
    en_to_cn[(h_full, a_full)] = (m.get('home_cn',''), m.get('away_cn',''))

def get_cn(h_en, a_en):
    """获取中文队名, 短名模糊兜底(HJK→HJK Helsinki) → TEAM_CN兜底(8-14汉化补漏: today.json home_cn为空时不再漏英文)"""
    if (h_en, a_en) in en_to_cn:
        hcn, acn = en_to_cn[(h_en, a_en)]
        if hcn and acn:
            return (hcn, acn)
    # 子串模糊匹配
    for (kh, ka), (hcn, acn) in en_to_cn.items():
        if (h_en in kh or kh in h_en) and (a_en in ka or ka in a_en):
            if hcn and acn:
                return (hcn, acn)
    # TEAM_CN兜底 (home_cn字段缺失时)
    from pipeline.reporter import TEAM_CN
    return (TEAM_CN.get(h_en, h_en), TEAM_CN.get(a_en, a_en))

# -- 加载模型预测 --
pred_path = f'data/output/predictions_{date_str}.json'
preds = json.loads(Path(pred_path).read_text(encoding='utf-8')) if Path(pred_path).exists() else []

# -- 加载三线赔率 (缺失则回退体彩SPF) --
pinnacle = []
if Path(odds_file).exists():
    pinnacle = json.loads(Path(odds_file).read_text(encoding='utf-8'))
    print(f'赔率数据已加载: {odds_file} ({len(pinnacle)}场)')
else:
    print(f'赔率文件未找到: {odds_file}, 回退体彩SPF(today_matches_v3.json)')
    # 从体彩SPF赔率构造兼容结构
    for m in matches:
        odds = m.get('odds', {})
        if not odds: continue
        entry = {
            'home_team': m['home_team'],
            'away_team': m['away_team'],
            'bookmakers': [{
                'key': 'pinnacle',
                'markets': [
                    {'key': 'h2h', 'outcomes': [
                        {'name': m['home_team'], 'price': odds['home']},
                        {'name': 'Draw', 'price': odds['draw']},
                        {'name': m['away_team'], 'price': odds['away']}
                    ]}
                ]
            }]
        }
        pinnacle.append(entry)

source_label = '体彩三线' if (pinnacle and pinnacle[0].get('source') == '体彩三线') else ('Pinnacle' if Path(odds_file).exists() else '体彩SPF')

# -- 构建赔率查找表 --
pinn_map = {}
for e in pinnacle:
    h_raw = e['home_team']; a_raw = e['away_team']
    h_en = PINNACLE_NAME_MAP.get(h_raw, h_raw)
    a_en = PINNACLE_NAME_MAP.get(a_raw, a_raw)
    odds = {'h2h': None, 'ah': None, 'ou': None}
    for bm in e.get('bookmakers', []):
        if 'pinnacle' not in bm.get('key','').lower(): continue
        for mkt in bm['markets']:
            if mkt['key'] == 'h2h':
                o = {x['name']: x['price'] for x in mkt['outcomes']}
                raw = {'home': o.get(h_raw), 'draw': o.get('Draw'), 'away': o.get(a_raw)}
                if all(v and v > 0 for v in raw.values()):
                    fair, margin = shin_1x2(raw['home'], raw['draw'], raw['away'])
                    odds['h2h'] = {'raw': raw, 'fair': fair, 'margin': margin}
            elif mkt['key'] == 'spreads':
                for x in mkt['outcomes']:
                    nm = x['name']; pt = x.get('point', 0); pr = x['price']
                    if nm == h_raw:
                        odds['ah'] = {'home_pt': pt, 'home_price': pr, 'away_price': 0, 'away_pt': 0}
                    else:
                        if odds['ah'] is None: odds['ah'] = {}
                        odds['ah']['away_pt'] = pt; odds['ah']['away_price'] = pr
                if odds['ah'] and odds['ah'].get('home_price') and odds['ah'].get('away_price'):
                    fair_ah, _ = shin_binary(odds['ah']['home_price'], odds['ah']['away_price'])
                    odds['ah']['fair_home'] = fair_ah[0]; odds['ah']['fair_away'] = fair_ah[1]
            elif mkt['key'] == 'totals':
                for x in mkt['outcomes']:
                    if x['name'] == 'Over':
                        odds['ou'] = {'line': x['point'], 'over_price': x['price']}
                    elif x['name'] == 'Under':
                        if odds['ou'] is None: odds['ou'] = {}
                        odds['ou']['under_price'] = x['price']
                if odds['ou'] and odds['ou'].get('over_price') and odds['ou'].get('under_price'):
                    fair_ou, _ = shin_binary(odds['ou']['over_price'], odds['ou']['under_price'])
                    odds['ou']['fair_over'] = fair_ou[0]; odds['ou']['fair_under'] = fair_ou[1]
    pinn_map[(h_en, a_en)] = odds

# 兜底: 对未匹配预测做模糊匹配
def fuzzy_pinnacle(h, a):
    """预测队名→赔率条目模糊匹配, 处理乱码字符"""
    h_clean = h.lower().replace(' ','').replace('-','').replace('.','')
    a_clean = a.lower().replace(' ','').replace('-','').replace('.','')
    # 去非ASCII(处理乱码ü/é等)
    h_ascii = ''.join(c for c in h_clean if ord(c) < 128)
    a_ascii = ''.join(c for c in a_clean if ord(c) < 128)
    for (kh, ka) in pinn_map:
        kh_clean = kh.lower().replace(' ','').replace('-','').replace('.','')
        ka_clean = ka.lower().replace(' ','').replace('-','').replace('.','')
        kh_ascii = ''.join(c for c in kh_clean if ord(c) < 128)
        ka_ascii = ''.join(c for c in ka_clean if ord(c) < 128)
        # 纯ASCII前缀匹配
        if len(h_ascii) >= 4 and len(a_ascii) >= 4:
            if h_ascii[:6] in kh_ascii or kh_ascii[:6] in h_ascii:
                if a_ascii[:6] in ka_ascii or ka_ascii[:6] in a_ascii:
                    return (kh, ka)
    return None

for p in preds:
    h, a = p['home_team'], p['away_team']
    if (h, a) not in pinn_map:
        r = fuzzy_pinnacle(h, a)
        if r:
            pinn_map[(h, a)] = pinn_map[r]
            print('模糊匹配: {} vs {} -> {} vs {}'.format(h, a, r[0], r[1]))

matched = sum(1 for p in preds if (p['home_team'], p['away_team']) in pinn_map)
print('赔率覆盖率: {}/{}'.format(matched, len(preds)))
for p in preds:
    if (p['home_team'], p['away_team']) not in pinn_map:
        print('  无赔率: {} vs {} ({})'.format(p['home_team'], p['away_team'], p['league_code']))

# -- 维度门禁: 模型Brier < 气候基线才过门; 样本<30或未过门 → 禁注 --
def load_dim_gates():
    try:
        from pipeline.dimension_review import _climatology_brier
        import json as _json
        led = _json.load(open('data/state/dimension_ledger.json', encoding='utf-8'))
        gates = {}
        for dim, d in led.get('dimensions', {}).items():
            n = d.get('n', 0)
            if n >= 30:
                clim = _climatology_brier(d.get('samples', []), dim)
                gates[dim] = d['brier'] < clim
            else:
                gates[dim] = False   # 样本不足30 → 视为未过门禁
        return gates
    except Exception:
        return {}

gates = load_dim_gates()
_gate_txt = {k: ('✅' if v else '❌') for k, v in gates.items()}
print('维度门禁: 1X2{} OU25{} OU35{} BTTS{} AH{}(3样本)'.format(
    _gate_txt.get('1X2', '—'), _gate_txt.get('OU25', '—'), _gate_txt.get('OU35', '—'),
    _gate_txt.get('BTTS', '—'), _gate_txt.get('AH', '—')))

# -- Generate bets --
BETS = []
for p in preds:
    h, a = p['home_team'], p['away_team']
    lc = p['league_code']; cs = p['cold_start']
    h_cn, a_cn = get_cn(h, a)
    m = p['model']; sd = m.get('score_distribution', {})
    dc_h, dc_d, dc_a = m['home_win'], m['draw'], m['away_win']

    # 先精确后模糊短名(如 HJK→HJK Helsinki)
    po = pinn_map.get((h, a))
    if po is None:
        for (kh, ka), v in pinn_map.items():
            if (h in kh or kh in h) and (a in ka or ka in a):
                po = v; break
    if po is None: po = {}
    ph = po.get('h2h'); pa = po.get('ah'); pu = po.get('ou')
    dc_tot = totals_probs(sd) if sd else None
    candidates = []

    # === 维度1: 胜平负 ===
    if ph:
        fair = ph['fair']
        edges = {'home': dc_h-fair[0], 'draw': dc_d-fair[1], 'away': dc_a-fair[2]}
        best = max(edges, key=edges.get)
        edge_val = edges[best]
        kelly = max(0, edge_val)
        model_prob = {'home': dc_h, 'draw': dc_d, 'away': dc_a}[best]
        raw_odd = ph['raw'][best]
        # 真实EV门禁(8-14终盘B确立): 低赔大热时抽水集中 → 概率edge被真实赔率吃光
        # 必须 model_prob × 实际赔率 > 1 才是真价值 (否则是8月9日"临场飙升≠价值"教训的机械化翻版)
        ev_ok = model_prob * raw_odd > 1.0
        # 翻市场纪律(8-13确立): 模型方向≠市场方向 → 需双重证据(置信≥60%+结构性理由)
        # 当前分歧胜率2-2 → 模型尚无翻市场资格 → 一律拦截
        m_dir = max(('home', dc_h), ('draw', dc_d), ('away', dc_a), key=lambda x: x[1])[0]
        k_dir = min(ph['raw'].items(), key=lambda kv: kv[1])[0]
        if m_dir != k_dir:
            print('  [翻市场拦截] {} vs {} 胜平负 → 模型{}方向({:.1%})≠市场({:.2f}赔率最低), 无翻市场资格'.format(
                h, a, DIRMAP[m_dir], {'home': dc_h, 'draw': dc_d, 'away': dc_a}[m_dir], ph['raw'][k_dir]))
        elif not ev_ok:
            print('  [EV门禁拦截] {} vs {} 胜平负{} → 模型{:.1%}×赔率{:.2f}={:.3f}≤1 真实EV为负(抽水吃光edge)'.format(
                h, a, DIRMAP[best], model_prob, raw_odd, model_prob * raw_odd))
        # 终盘筛选: edge>5% + Kelly>1% + 非冷启动 + 方向概率>=35% + 真实EV>0
        elif kelly > 0.01 and edge_val > 0.05 and not cs and model_prob >= 0.35 and gates.get('1X2', True):
            candidates.append(('胜平负', DIRMAP[best], kelly, ph['raw'][best]))

    # === 维度2: 亚洲盘 ===
    if pa and sd and pa.get('fair_home'):
        home_pt = pa['home_pt']
        dc_hp = handicap_probs(sd, home_pt)
        dc_home_edge = dc_hp['home'] - pa['fair_home']
        dc_away_edge = dc_hp['away'] - pa['fair_away']
        if not gates.get('AH', True):
            print('  [门禁拦截] {} vs {} 亚洲盘 → AH维度未过门禁'.format(h, a))

        if dc_home_edge > 0 and dc_home_edge > dc_away_edge:
            kelly = dc_home_edge
            if home_pt > 0.01: label = '主队(受+{:.2f})'.format(home_pt)
            elif home_pt < -0.01: label = '主队(让{:.2f})'.format(-home_pt)
            else: label = '主队(平手)'
            if kelly > 0.01 and dc_home_edge > 0.05 and not cs and dc_hp['home'] >= 0.35 and gates.get('AH', True):
                candidates.append(('亚洲盘', label, kelly, pa['home_price']))
        elif dc_away_edge > 0:
            kelly = dc_away_edge
            away_pt = pa.get('away_pt', -home_pt)
            if away_pt > 0.01: label = '客队(受+{:.2f})'.format(away_pt)
            elif away_pt < -0.01: label = '客队(让{:.2f})'.format(-away_pt)
            else: label = '客队(平手)'
            if kelly > 0.01 and dc_away_edge > 0.05 and not cs and dc_hp['away'] >= 0.35 and gates.get('AH', True):
                candidates.append(('亚洲盘', label, kelly, pa['away_price']))

    # === 维度3: 大小球 ===
    if pu and dc_tot and pu.get('fair_over'):
        line = pu['line']
        # 按赔率线插值DC模型概率
        if abs(line - 2.5) < 0.15: dc_over = dc_tot['over_2_5']
        elif abs(line - 3.5) < 0.15: dc_over = dc_tot['over_3_5']
        elif abs(line - 3.0) < 0.15: dc_over = dc_tot.get('over_2_5', 0.5) * 0.8
        elif abs(line - 2.75) < 0.15: dc_over = dc_tot.get('over_2_5', 0.5) * 0.85
        elif abs(line - 3.25) < 0.15: dc_over = dc_tot.get('over_3_5', 0.3) * 1.1
        elif abs(line - 2.25) < 0.15: dc_over = dc_tot.get('over_2_5', 0.5) * 1.15
        elif abs(line - 1.75) < 0.15: dc_over = dc_tot.get('over_2_5', 0.5) * 0.7
        else: dc_over = 0.5
        over_edge = dc_over - pu['fair_over']
        under_edge = (1-dc_over) - pu['fair_under']
        # 维度门禁: 线2.5→OU25, 线3.5→OU35, 未过门禁维度禁注
        ou_dim = 'OU25' if abs(line - 2.5) < 0.3 else ('OU35' if abs(line - 3.5) < 0.3 else None)
        ou_gate = gates.get(ou_dim, True) if ou_dim else True
        if not ou_gate:
            print('  [门禁拦截] {} vs {} 大小球线{} → {}维度未过门禁'.format(h, a, line, ou_dim))
        if over_edge > under_edge and over_edge > 0:
            if over_edge > 0.05 and not cs and dc_over >= 0.35 and ou_gate:
                candidates.append(('大小球', '大{:.1f}球'.format(line), over_edge, pu['over_price']))
        elif under_edge > 0:
            if under_edge > 0.05 and not cs and (1-dc_over) >= 0.35 and ou_gate:
                candidates.append(('大小球', '小{:.1f}球'.format(line), under_edge, pu['under_price']))

    if not candidates: continue

    best = max(candidates, key=lambda x: x[2])
    dim, direction, kelly, odds_val = best

    kf = min(kelly * KF, 0.05)
    if cs: kf = min(kf, 0.02)
    stake = int(BANKROLL * kf)

    BETS.append({
        'home': h_cn, 'away': a_cn, 'league': LEAGUE_CN.get(lc, lc),
        'dim': dim, 'direction': direction, 'kelly': kelly,
        'odds': odds_val, 'stake': stake, 'cold': cs,
    })

# 总仓位上限25%
total = sum(b['stake'] for b in BETS)
if total > 2500:
    s = 2500.0 / total
    for b in BETS: b['stake'] = int(b['stake'] * s)
total = sum(b['stake'] for b in BETS)

# -- Display --
print()
print('=' * 95)
print('  JOYBOY | {} 三线合并预测 | 1X2+亚洲盘+大小球 | Shin去水 | 1/4 Kelly{}'.format(
    date_str, f' | {time_window}窗口' if time_window else ''))
print('=' * 95)
for b in BETS:
    o = '{:.2f}'.format(b['odds']) if b['odds'] else '  --'
    tag = '冷启动 ' if b['cold'] else '      '
    print('  {}{} vs {} | {} | {} | {} @{} Kelly={:.0%} ¥{}'.format(
        tag, b['home'], b['away'], b['league'], b['dim'], b['direction'],
        o, b['kelly'], b['stake']))
print('=' * 95)
print('  {}注 | ¥{:,} | {:.1f}%仓位 | 数据源: {}'.format(
    len(BETS), total, total/BANKROLL*100, source_label))
dims = {}
for b in BETS: dims[b['dim']] = dims.get(b['dim'], 0) + 1
print('  维度分布: {}'.format(dims))

# Save
out = Path(f'data/output/pinnacle_bets_{date_str}.json')
out.write_text(json.dumps({'date':date_str,'bets':BETS,'total':total,'source':source_label},
    ensure_ascii=False, indent=2), encoding='utf-8')
print('\n已保存: ' + str(out))
