"""从体彩官网拉取今日三线赔率 (SPF + 让球 + 总进球) → 写入 today.json"""
import sys, io, json, httpx, pathlib
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y-%m-%d')
beijing_tz = timezone(timedelta(hours=8))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.sporttery.cn/',
}

# Step 1: Fetch all 3 pools
all_matches = {}

for pool in ['HAD', 'HHAD', 'TTG']:
    url = f'https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?poolCode={pool}&channelId=500'
    with httpx.Client(timeout=15, verify=False) as client:
        data = client.get(url, headers=headers).json()
    mlist = data['value']['matchInfoList']
    for db in mlist:
        for m in db.get('subMatchList', []):
            if m['businessDate'] != date_str:
                continue
            mid = m['matchId']
            if mid not in all_matches:
                league_name = m.get('leagueName') or m.get('leagueAbbName') or ''
                all_matches[mid] = {
                    'home': m['homeTeamAllName'],
                    'away': m['awayTeamAllName'],
                    'home_abb': m.get('homeTeamAbbName', ''),
                    'away_abb': m.get('awayTeamAbbName', ''),
                    'league_name': league_name,
                    'league_id': m.get('leagueId', ''),
                    'match_num': m.get('matchNumCode', ''),
                }
            if pool == 'HAD':
                all_matches[mid]['had'] = m.get('had', {})
            elif pool == 'HHAD':
                all_matches[mid]['hhad'] = m.get('hhad', {})
            else:
                all_matches[mid]['ttg'] = m.get('ttg', {})

print(f'体彩 {date_str} 比赛: {len(all_matches)}场')

# Step 2: Build today.json entries
# Map 体彩 league names to internal codes
LEAGUE_CN_TO_CODE = {
    '英格兰超级联赛': 'PL',
    '西班牙甲级联赛': 'PD',
    '德国甲级联赛': 'BL1',
    '意大利甲级联赛': 'SA',
    '法国甲级联赛': 'FL1',
    '荷兰甲级联赛': 'DED',
    '葡萄牙超级联赛': 'PPL',
    '日本职业联赛': 'J1',
    '韩国职业联赛': 'KLEAGUE',
    '巴西甲级联赛': 'BSA',
    '瑞典超级联赛': 'SWE',
    '挪威超级联赛': 'NO1',
    '欧洲冠军联赛': 'UCL',
    '欧罗巴联赛': 'UEL',
    '英格兰冠军联赛': 'ELC',
    '美国职业大联盟': 'MLS',
}

# Chinese → English team name mapping for common teams
CN_TO_EN_TEAM = {
    '巴黎圣日尔曼': 'Paris Saint-Germain',
    '阿斯顿维拉': 'Aston Villa',
    '普拉滕斯': 'Platense',
    '科金博联': 'Coquimbo Unido',
    '帕尔梅拉斯': 'Palmeiras',
    '波特诺山丘': 'Cerro Porteno',
    '皇家马德里': 'Real Madrid',
    '巴塞罗那': 'Barcelona',
    '拜仁慕尼黑': 'Bayern Munich',
    '曼城': 'Manchester City',
    '利物浦': 'Liverpool',
    '阿森纳': 'Arsenal',
    '切尔西': 'Chelsea',
    '多特蒙德': 'Borussia Dortmund',
    '国际米兰': 'Inter Milan',
    'AC米兰': 'AC Milan',
    '尤文图斯': 'Juventus',
    '马德里竞技': 'Atletico Madrid',
    '博卡青年': 'Boca Juniors',
    '河床': 'River Plate',
    '弗拉门戈': 'Flamengo',
    '圣保罗': 'Sao Paulo',
    '桑托斯': 'Santos',
}

# Fallback: try to match by league name substring, then by team name
def guess_league_code(name, home, away):
    if name:
        for cn, code in LEAGUE_CN_TO_CODE.items():
            if cn in name or name in cn:
                return code
    # Team-based guessing for common intl club competitions
    big_euro = {'巴黎圣日尔曼','皇家马德里','巴塞罗那','拜仁慕尼黑','曼城','利物浦','阿斯顿维拉','阿森纳','切尔西','多特蒙德','国际米兰','AC米兰','尤文图斯'}
    if home in big_euro or away in big_euro:
        if any(t in {'巴黎圣日尔曼','阿斯顿维拉','皇家马德里'} for t in [home, away]):
            return 'UCL'  # UEFA CL
    # CONMEBOL
    south_american = {'帕尔梅拉斯','波特诺山丘','博卡青年','河床','弗拉门戈'}
    if home in south_american or away in south_american:
        return 'CLB'  # Libertadores
    # Check for Sudamericana teams
    if any(team in ['普拉滕斯','科金博联'] for team in [home, away]):
        return 'CSD'
    return 'UNK'

today = []
for mid, m in sorted(all_matches.items(), key=lambda x: x[1].get('match_num', '')):
    had = m.get('had', {})
    hhad = m.get('hhad', {})
    ttg = m.get('ttg', {})

    home_cn = m['home']
    away_cn = m['away']
    home = CN_TO_EN_TEAM.get(home_cn, home_cn)
    away = CN_TO_EN_TEAM.get(away_cn, away_cn)
    lc = guess_league_code(m.get('league_name', ''), home_cn, away_cn)

    entry = {
        'home_team': home,
        'away_team': away,
        'league_code': lc,
        'league_name': m.get('league_name', ''),
        'match_num': m.get('match_num', ''),
    }

    # SPF odds
    if had.get('h'):
        entry['odds'] = {
            'home': float(had['h']),
            'draw': float(had['d']),
            'away': float(had['a']),
        }

    # Asian Handicap
    if hhad.get('goalLine'):
        gl = float(hhad['goalLine'])
        entry['handicap'] = gl  # negative = home gives
        entry['ah_odds'] = {
            'home': float(hhad['h']),
            'draw': float(hhad['d']),
            'away': float(hhad['a']),
        }

    # Total goals exact → derive O/U 2.5
    if ttg.get('s0'):
        tg_odds = {}
        for k in ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7']:
            if k in ttg:
                tg_odds[k] = float(ttg[k])
        entry['total_goals_odds'] = tg_odds

        # Derive over/under 2.5: over = P(3+) = s3 + s4 + s5 + s6 + s7
        # First devig: compute raw implied probs
        total_prob = sum(1/o for o in tg_odds.values())
        over_raw = sum(1/tg_odds[k] for k in ['s3', 's4', 's5', 's6', 's7'] if k in tg_odds)
        under_raw = sum(1/tg_odds[k] for k in ['s0', 's1', 's2'] if k in tg_odds)

        if total_prob > 0:
            devig_factor = 1.0 / total_prob
            fair_over_prob = over_raw * devig_factor
            fair_under_prob = under_raw * devig_factor
            # Convert fair probs back to decimal odds
            if fair_over_prob > 0:
                entry['ou_line'] = 2.5
                entry['over_odds'] = round(1.0 / fair_over_prob, 2)
                entry['under_odds'] = round(1.0 / fair_under_prob, 2) if fair_under_prob > 0 else 99.0

    today.append(entry)

    # Print match summary
    print(f'\n[{m["match_num"]}] {home} vs {away}')
    print(f'  联赛: {m["league_name"]} → {lc}')
    if entry.get('odds'):
        o = entry['odds']
        print(f'  SPF(体彩): {o["home"]:.2f} / {o["draw"]:.2f} / {o["away"]:.2f}')
    if entry.get('handicap'):
        gl = entry['handicap']
        sign = f'主让{abs(int(gl))}球' if gl < 0 else f'主受{int(gl)}球'
        ah = entry['ah_odds']
        print(f'  让球({sign}): 主{ah["home"]:.2f} / 平{ah["draw"]:.2f} / 客{ah["away"]:.2f}')
    if entry.get('ou_line'):
        print(f'  大小(O/U 2.5): 大{entry["over_odds"]:.2f} / 小{entry["under_odds"]:.2f}')

# Save
pathlib.Path('data/today.json').write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\n✅ 保存 {len(today)} 场到 data/today.json')

# Also save in pinnacle-compatible format for run_pinnacle_bets.py
pinnacle_format = []
for m in today:
    if not m.get('odds'):
        continue
    o = m['odds']
    entry = {
        'home_team': m['home_team'],
        'away_team': m['away_team'],
        'bookmakers': [{'key': 'pinnacle', 'markets': [
            {'key': 'h2h', 'outcomes': [
                {'name': m['home_team'], 'price': o['home']},
                {'name': 'Draw', 'price': o['draw']},
                {'name': m['away_team'], 'price': o['away']},
            ]}
        ]}]
    }
    # Add handicap if available
    if m.get('handicap') is not None and m.get('ah_odds'):
        ah = m['ah_odds']
        gl = m['handicap']
        entry['bookmakers'][0]['markets'].append({
            'key': 'spreads', 'outcomes': [
                {'name': m['home_team'], 'price': ah['home'], 'point': gl},
                {'name': m['away_team'], 'price': ah['away'], 'point': -gl},
            ]
        })
    # Add totals if available
    if m.get('ou_line') and m.get('over_odds'):
        entry['bookmakers'][0]['markets'].append({
            'key': 'totals', 'outcomes': [
                {'name': 'Over', 'price': m['over_odds'], 'point': m['ou_line']},
                {'name': 'Under', 'price': m['under_odds'], 'point': m['ou_line']},
            ]
        })
    pinnacle_format.append(entry)

odds_path = pathlib.Path(f'data/pinnacle_odds_{date_str}.json')
odds_path.write_text(json.dumps(pinnacle_format, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'✅ 保存 {len(pinnacle_format)} 场三线赔率到 {odds_path}')
