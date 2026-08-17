"""从体彩官网拉取今日三线赔率 (SPF + 让球 + 总进球) → 写入 today.json"""
import sys, io, json, re, urllib.request, ssl, time, pathlib
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

date_str = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else datetime.now().strftime('%Y-%m-%d')
include_all = "--all" in sys.argv  # 全量模式: 体彩开盘的所有比赛(含非五大联赛)
beijing_tz = timezone(timedelta(hours=8))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.sporttery.cn/',
}

# httpx走系统代理常SSL断连 → urllib直连+重试
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),      # 禁用系统代理
    urllib.request.HTTPSHandler(context=_ctx),
)

def _get_json(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with _opener.open(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if i == retries - 1:
                raise
            print(f'  重试 {i+1}/{retries-1}: {e}')
            time.sleep(2)

# 第1步: 拉取三个彩池(HAD胜平负/HHAD让球/TTG总进球)
all_matches = {}

for pool in ['HAD', 'HHAD', 'TTG', 'CRS', 'HAFU']:
    url = f'https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?poolCode={pool}&channelId=500'
    data = _get_json(url)
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
                    'match_time': m.get('matchTime') or m.get('matchTime2') or '',
                }
            if pool == 'HAD':
                all_matches[mid]['had'] = m.get('had', {})
            elif pool == 'HHAD':
                all_matches[mid]['hhad'] = m.get('hhad', {})
            elif pool == 'TTG':
                all_matches[mid]['ttg'] = m.get('ttg', {})
            elif pool == 'CRS':
                all_matches[mid]['crs'] = m.get('crs', {})
            else:
                all_matches[mid]['hafu'] = m.get('hafu', {})

print(f'体彩 {date_str} 比赛: {len(all_matches)}场')

# 第2步: 组装 today.json 数据项
# Map 体彩 league names to internal codes
# 注意: 短名必须放在全名之前 (子串匹配先命中者胜, 如"西甲"会被"巴西甲级联赛"误吞)
LEAGUE_CN_TO_CODE = {
    '西甲': 'PD', '西甲联赛': 'PD',
    '英超': 'PL', '英冠': 'ELC',
    '德乙': 'BL2', '德甲': 'BL1',
    '荷甲': 'DED', '荷乙': 'DED2',
    '葡超': 'PPL', '法乙': 'FL2',
    '芬超': 'FIN', '瑞超': 'SWE', '挪超': 'NOR',
    '日职': 'J1', '韩职': 'KLEAGUE',
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
    '欧罗巴': 'UEL',
    '英格兰冠军联赛': 'ELC',
    '美国职业大联盟': 'MLS',
    '沙特职业联赛': 'SPL',
    '沙职': 'SPL',
    '日职': 'J1',
    '芬超': 'FIN',
    '德乙': 'BL2',
    '瑞超': 'SWE',
    '挪超': 'NOR',
    '荷甲': 'DED',
    '荷乙': 'DED2',
    '法乙': 'FL2',
    '英冠': 'ELC',
    '葡超': 'PPL',
}

# 中文→英文队名映射(常见球队)
from pipeline.team_names import CN_TO_EN_TEAM

# 兜底: 先按联赛名子串匹配, 再按队名
def guess_league_code(name, home, away):
    if name:
        for cn, code in LEAGUE_CN_TO_CODE.items():
            if cn in name or name in cn:
                return code
    # 按队名猜常见国际俱乐部赛事
    big_euro = {'巴黎圣日尔曼','皇家马德里','巴塞罗那','拜仁慕尼黑','曼城','利物浦','阿斯顿维拉','阿森纳','切尔西','多特蒙德','国际米兰','AC米兰','尤文图斯'}
    if home in big_euro or away in big_euro:
        if any(t in {'巴黎圣日尔曼','阿斯顿维拉','皇家马德里'} for t in [home, away]):
            return 'UCL'  # UEFA CL
    # CONMEBOL
    south_american = {'帕尔梅拉斯','波特诺山丘','博卡青年','河床','弗拉门戈',
                      '米拉索尔','基多体大','罗萨里奥','科林蒂安'}
    if home in south_american or away in south_american:
        return 'CLB'  # Libertadores
    # 南球杯球队检测
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
        'kickoff_time': m.get('match_time', ''),
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

    # 总进球精确赔率 → 推导大小2.5
    if ttg.get('s0'):
        tg_odds = {}
        for k in ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7']:
            if k in ttg:
                tg_odds[k] = float(ttg[k])
        entry['total_goals_odds'] = tg_odds

        # 大小2.5推导: 大 = P(3球以上) = s3+s4+s5+s6+s7
        # 先去水: 计算原始隐含概率
        total_prob = sum(1/o for o in tg_odds.values())
        over_raw = sum(1/tg_odds[k] for k in ['s3', 's4', 's5', 's6', 's7'] if k in tg_odds)
        under_raw = sum(1/tg_odds[k] for k in ['s0', 's1', 's2'] if k in tg_odds)

        if total_prob > 0:
            devig_factor = 1.0 / total_prob
            fair_over_prob = over_raw * devig_factor
            fair_under_prob = under_raw * devig_factor
            # 公平概率转回十进制赔率
            if fair_over_prob > 0:
                entry['ou_line'] = 2.5
                entry['over_odds'] = round(1.0 / fair_over_prob, 2)
                entry['under_odds'] = round(1.0 / fair_under_prob, 2) if fair_under_prob > 0 else 99.0

    # 波胆 (比分) 赔率
    crs = m.get('crs', {})
    if crs:
        cs_odds = {}
        for k, v in crs.items():
            mm = re.match(r's(\d+)s(\d+)$', k)
            if mm and v:
                try:
                    cs_odds[f"{int(mm.group(1))}-{int(mm.group(2))}"] = float(v)
                except (ValueError, TypeError):
                    pass
        if cs_odds:
            entry['correct_score_odds'] = cs_odds

    # 半全场赔率
    hafu = m.get('hafu', {})
    if hafu:
        names = {'hh': '主/主', 'hd': '主/平', 'ha': '主/客',
                 'dh': '平/主', 'dd': '平/平', 'da': '平/客',
                 'ah': '客/主', 'ad': '客/平', 'aa': '客/客'}
        ht_ft = {}
        for k, v in hafu.items():
            if k in names and v:
                try:
                    ht_ft[names[k]] = float(v)
                except (ValueError, TypeError):
                    pass
        if ht_ft:
            entry['ht_ft_odds'] = ht_ft

    today.append(entry)

    # 打印场次摘要
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

# 聚焦联赛过滤 (默认只关注五大联赛; --all 时纳入体彩开盘全部比赛)
try:
    from config import FOCUS_LEAGUES
    before = len(today)
    if not include_all:
        today = [m for m in today if m.get('league_code') in FOCUS_LEAGUES]
        print(f'聚焦联赛过滤: {before} → {len(today)} 场 (保留 {FOCUS_LEAGUES})')
    else:
        print(f'全量模式: 保留体彩开盘全部 {before} 场 (含非五大联赛, 分析为主)')
except Exception as e:
    print(f'聚焦联赛过滤跳过: {e}')

# Save
pathlib.Path('data/today.json').write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\n✅ 保存 {len(today)} 场到 data/today.json')

# 赔率快照 (早/午/终盘纪律: 记录每次拉取的时间点快照, 供赔率变动对比)
try:
    from datetime import datetime as _dt
    snap_dir = pathlib.Path('data/state/odds_snapshots')
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_name = f'snapshot_{date_str}_{_dt.now().strftime("%H%M")}.json'
    snap_path = snap_dir / snap_name
    # 同一天同时间的快照覆盖, 避免重复堆积
    for old in snap_dir.glob(f'snapshot_{date_str}_*.json'):
        if old.name == snap_name:
            old.unlink()
    snap_path.write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'📸 赔率快照已存 → {snap_path.name}')
except Exception as e:
    print(f'快照保存跳过: {e}')

# 另存pinnacle兼容格式供 run_pinnacle_bets.py 使用
pinnacle_format = []
for m in today:
    if not m.get('odds'):
        continue
    o = m['odds']
    entry = {
        'source': '体彩三线',   # 数据源标记: run_pinnacle_bets.py 据此标注
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
    # 有让球盘则加入
    if m.get('handicap') is not None and m.get('ah_odds'):
        ah = m['ah_odds']
        gl = m['handicap']
        entry['bookmakers'][0]['markets'].append({
            'key': 'spreads', 'outcomes': [
                {'name': m['home_team'], 'price': ah['home'], 'point': gl},
                {'name': m['away_team'], 'price': ah['away'], 'point': -gl},
            ]
        })
    # 有大小球则加入
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
