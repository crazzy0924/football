"""初盘 vs 临盘对比 — Pinnacle赔率变动检测 · 蒸汽移动 · 水位变化"""
import json, sys

OPENING = 'data/pinnacle_opening_20260809.json'
CLOSING = 'data/pinnacle_closing_20260809.json'

def get_odds(event, market_key):
    """Extract odds for a specific market from a Pinnacle event."""
    for bm in event.get('bookmakers', []):
        if 'pinnacle' not in bm.get('key','').lower(): continue
        for mkt in bm['markets']:
            if mkt['key'] == market_key: return mkt
    return None

def parse_h2h(mkt, home_team, away_team):
    """Parse 1X2 market → {home, draw, away} prices."""
    if not mkt: return None
    out = {}
    for x in mkt['outcomes']:
        if x['name'] == home_team: out['home'] = x['price']
        elif x['name'] == 'Draw': out['draw'] = x['price']
        elif x['name'] == away_team: out['away'] = x['price']
    return out if len(out) == 3 else None

def parse_ah(mkt, home_team):
    """Parse Asian handicap → (home_pt, home_price, away_pt, away_price)."""
    if not mkt: return None
    hp = ap = hp_pr = ap_pr = None
    for x in mkt['outcomes']:
        if x['name'] == home_team:
            hp = x.get('point', 0); hp_pr = x['price']
        else:
            ap = x.get('point', 0); ap_pr = x['price']
    if hp is not None and ap is not None:
        return {'home_pt': hp, 'home_price': hp_pr, 'away_pt': ap, 'away_price': ap_pr}
    return None

def parse_ou(mkt):
    """Parse totals → {line, over_price, under_price}."""
    if not mkt: return None
    out = {}
    for x in mkt['outcomes']:
        if x['name'] == 'Over':
            out['line'] = x.get('point'); out['over_price'] = x['price']
        elif x['name'] == 'Under':
            out['under_price'] = x['price']
    return out if 'line' in out and 'over_price' in out and 'under_price' in out else None

def price_to_implied(p):
    """Convert decimal odds to raw implied probability (no vig removal)."""
    return 1/p if p else 0

def arrow(v):
    """Direction arrow for change."""
    if v > 0.001: return '↑'
    if v < -0.001: return '↓'
    return '→'

with open(OPENING, 'r', encoding='utf-8') as f: opening = json.load(f)
with open(CLOSING, 'r', encoding='utf-8') as f: closing = json.load(f)

# Build lookup by (home, away)
open_map = {(e['home_team'], e['away_team']): e for e in opening}
close_map = {(e['home_team'], e['away_team']): e for e in closing}

# Find matches present in BOTH (exclude already-kicked)
common_keys = set(open_map.keys()) & set(close_map.keys())
kicked = set(open_map.keys()) - set(close_map.keys())
new_added = set(close_map.keys()) - set(open_map.keys())

print('=' * 105)
print('  📊 Pinnacle 初盘 vs 临盘 · 赔率变动检测')
print('=' * 105)
print(f'  共同场次: {len(common_keys)} | 已开踢: {len(kicked)} | 新增: {len(new_added)}')
if kicked:
    kicked_names = [f'{h} vs {a}' for h,a in kicked]
    print(f'  已开踢: {", ".join(kicked_names)}')

# Analyze each common match
movements = []
for key in sorted(common_keys):
    h, a = key
    o_e = open_map[key]; c_e = close_map[key]

    o_h2h = get_odds(o_e, 'h2h'); c_h2h = get_odds(c_e, 'h2h')
    o_ah = get_odds(o_e, 'spreads'); c_ah = get_odds(c_e, 'spreads')
    o_ou = get_odds(o_e, 'totals'); c_ou = get_odds(c_e, 'totals')

    h2h_o = parse_h2h(o_h2h, h, a); h2h_c = parse_h2h(c_h2h, h, a)
    ah_o = parse_ah(o_ah, h); ah_c = parse_ah(c_ah, h)
    ou_o = parse_ou(o_ou); ou_c = parse_ou(c_ou)

    lines = []
    steam_flags = []

    # ── 1X2 comparison ──
    if h2h_o and h2h_c:
        h_chg = price_to_implied(h2h_c['home']) - price_to_implied(h2h_o['home'])
        d_chg = price_to_implied(h2h_c['draw']) - price_to_implied(h2h_o['draw'])
        a_chg = price_to_implied(h2h_c['away']) - price_to_implied(h2h_o['away'])
        max_chg = max(abs(h_chg), abs(d_chg), abs(a_chg))
        lines.append(f'1X2: H {h2h_o["home"]:.2f}→{h2h_c["home"]:.2f} ({h_chg:+.1%})  '
                     f'D {h2h_o["draw"]:.2f}→{h2h_c["draw"]:.2f} ({d_chg:+.1%})  '
                     f'A {h2h_o["away"]:.2f}→{h2h_c["away"]:.2f} ({a_chg:+.1%})')
        if max_chg > 0.03:
            # Which direction moved most?
            dirs = {'主胜': h_chg, '平局': d_chg, '客胜': a_chg}
            top = max(dirs, key=lambda x: abs(dirs[x]))
            steam_flags.append(f'🔥 1X2蒸汽: {top} {dirs[top]:+.1%}')

    # ── AH comparison ──
    if ah_o and ah_c:
        ah_o_str = f'{ah_o["home_pt"]:+.2f} ({ah_o["home_price"]:.2f}/{ah_o["away_price"]:.2f})'
        ah_c_str = f'{ah_c["home_pt"]:+.2f} ({ah_c["home_price"]:.2f}/{ah_c["away_price"]:.2f})'
        pt_chg = ah_c['home_pt'] - ah_o['home_pt']
        hp_chg = ah_c['home_price'] - ah_o['home_price']
        ap_chg = ah_c['away_price'] - ah_o['away_price']
        lines.append(f'AH:  {ah_o_str} → {ah_c_str}  '
                     f'盘口{pt_chg:+.2f}  主赔{hp_chg:+.2f}  客赔{ap_chg:+.2f}')
        if abs(pt_chg) >= 0.25:
            steam_flags.append(f'🔥 AH盘口移动: {pt_chg:+.2f}球')
        if abs(hp_chg) >= 0.15:
            side = '主队' if hp_chg < 0 else '客队'
            steam_flags.append(f'🔥 AH水位骤变: {side}赔{"降" if hp_chg < 0 else "升"}{abs(hp_chg):.2f}')

    # ── OU comparison ──
    if ou_o and ou_c:
        line_chg = ou_c['line'] - ou_o['line']
        ov_chg = ou_c['over_price'] - ou_o['over_price']
        un_chg = ou_c['under_price'] - ou_o['under_price']
        lines.append(f'OU:  {ou_o["line"]:.1f} O{ou_o["over_price"]:.2f}/U{ou_o["under_price"]:.2f} → '
                     f'{ou_c["line"]:.1f} O{ou_c["over_price"]:.2f}/U{ou_c["under_price"]:.2f}  '
                     f'线{line_chg:+.1f}  O赔{ov_chg:+.2f}  U赔{un_chg:+.2f}')
        if abs(line_chg) >= 0.5:
            steam_flags.append(f'🔥 OU盘口移动: {line_chg:+.1f}球')
        if abs(ov_chg) >= 0.15:
            steam_flags.append(f'🔥 OU大球赔率{"降" if ov_chg < 0 else "升"}{abs(ov_chg):.2f}')

    match_name = f'{h[:22]} vs {a[:22]}'
    print(f'\n{"─"*105}')
    print(f'  {match_name}')
    for line in lines:
        print(f'    {line}')
    if steam_flags:
        for sf in steam_flags:
            print(f'    {sf}')
    else:
        print(f'    无明显变动')

    # Score movement
    score = 0
    if steam_flags: score = len(steam_flags)
    movements.append({'match': match_name, 'score': score, 'flags': steam_flags})

print(f'\n{"="*105}')
print(f'  📈 变动汇总')
print(f'{"="*105}')
steamers = [m for m in movements if m['score'] > 0]
if steamers:
    for m in sorted(steamers, key=lambda x: -x['score']):
        print(f'  [{m["score"]}🔥] {m["match"]}')
        for f in m['flags']:
            print(f'         {f}')
else:
    print(f'  无显著赔率变动 — 初盘到临盘水位稳定')
print(f'\n  注: 🔥 = 蒸汽移动信号 (概率变动>3% 或 盘口移动≥0.25球 或 水位变动≥0.15)')
