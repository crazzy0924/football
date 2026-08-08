#!/usr/bin/env python3
"""午盘分析: 拉取最新赔率 → 对比早盘 → 检测蒸汽移动 → 更新tracking"""
import json, sys, time, io
from datetime import datetime
from pathlib import Path
import requests

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.lottery.gov.cn/',
}

def fetch_latest_odds(date_str="2026-08-08"):
    """拉取体彩官方最新赔率"""
    url = 'https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry'
    r = requests.get(url, params={'matchDate': date_str}, headers=HEADERS, timeout=30)
    raw = r.json()

    odds_by_num = {}
    if raw.get('success'):
        for mil in raw.get('value', {}).get('matchInfoList', []):
            for m in mil.get('subMatchList', []):
                mn = m.get('matchNum', 0)
                odds = {}
                for key in ['had', 'hhad', 'ttg', 'crs', 'hafu']:
                    if key in m and m[key]:
                        odds[key] = m[key]
                odds_by_num[mn] = {
                    'homeTeam': m.get('homeTeamAllName', ''),
                    'awayTeam': m.get('awayTeamAllName', ''),
                    'homeRank': m.get('homeRank', ''),
                    'awayRank': m.get('awayRank', ''),
                    'odds': odds,
                    'matchStatus': m.get('matchStatus', ''),
                }
    return odds_by_num

def analyze():
    print("═══ 午盘分析 (16:00) ═══")
    print()

    # 1. 读取早盘基准
    tracking = json.loads(open(ROOT / 'daily_tracking.json', encoding='utf-8').read())
    print(f"早盘基准: {tracking['total_matches']} 场 @ {tracking['generated_at']}")

    # 2. 拉取最新赔率
    print("拉取体彩官方最新赔率...")
    latest = fetch_latest_odds()
    print(f"获取到 {len(latest)} 场比赛")

    # 3. 逐场对比
    signals = []
    updated_matches = []

    for bm in tracking['matches']:
        mid = bm['match_id']
        mid_int = int(mid) + 6000  # 体彩matchNum

        lot = latest.get(mid_int)
        if not lot:
            updated_matches.append(bm)
            continue

        old_spf = bm.get('official_spf')
        new_had = lot['odds'].get('had', {})
        old_hhad = bm.get('official_hhad') or {}
        new_hhad = lot['odds'].get('hhad', {})

        home_cn = bm['home_team_cn']
        away_cn = bm['away_team_cn']
        league = bm['league_cn']

        # SPF对比
        spf_changes = {}
        alerts = []

        if old_spf and new_had:
            oh, od, oa = float(old_spf['h']), float(old_spf['d']), float(old_spf['a'])
            nh, nd, na = float(new_had['h']), float(new_had['d']), float(new_had['a'])

            # 水位变化 = (新概率 - 旧概率) / 旧概率
            dh = ((1/nh)/(1/oh) - 1) * 100
            dd = ((1/nd)/(1/od) - 1) * 100
            da = ((1/na)/(1/oa) - 1) * 100

            spf_changes = {'home': round(dh, 1), 'draw': round(dd, 1), 'away': round(da, 1)}

            for label, chg, direction in [('主胜', dh, 'home'), ('平局', dd, 'draw'), ('客胜', da, 'away')]:
                if chg > 8:
                    alerts.append(f'🔥🔥 {label}赔率骤降{chg:.0f}% → 蒸汽移动')
                elif chg > 5:
                    alerts.append(f'🔥 {label}赔率走低{chg:.0f}% → 资金涌入')
                elif chg > 3:
                    alerts.append(f'📈 {label}微降{chg:.0f}%')
                elif chg < -8:
                    alerts.append(f'💧 {label}赔率拉升{abs(chg):.0f}% → 资金流出')

        # 亚盘对比
        old_gl = old_hhad.get('goalLine', '') or bm.get('handicap_official', '')
        new_gl = new_hhad.get('goalLine', '') if new_hhad else ''
        handicap_change = None
        if old_gl and new_gl and old_gl != new_gl:
            alerts.append(f'⚡ 盘口变化: {old_gl} → {new_gl}')
            handicap_change = f'{old_gl}→{new_gl}'

        # 更新比赛数据
        bm_updated = dict(bm)
        if new_had:
            bm_updated['official_spf'] = {
                'h': new_had['h'], 'd': new_had['d'], 'a': new_had['a'],
                'updateTime': new_had.get('updateTime', ''),
                'updateDate': new_had.get('updateDate', '')
            }
        if new_hhad:
            bm_updated['official_hhad'] = {
                'h': new_hhad['h'], 'd': new_hhad['d'], 'a': new_hhad['a'],
                'goalLine': new_hhad.get('goalLine', ''),
                'updateTime': new_hhad.get('updateTime', '')
            }
        bm_updated['afternoon_spf_changes'] = spf_changes
        bm_updated['afternoon_alerts'] = alerts
        bm_updated['afternoon_checked_at'] = datetime.now().isoformat()

        if alerts:
            bm_updated['afternoon_signal'] = True
        updated_matches.append(bm_updated)

        if alerts:
            print(f"{'='*60}")
            print(f"🎯 {mid} {home_cn} vs {away_cn} ({league})")
            if old_spf and new_had:
                print(f"   SPF: {oh}/{od}/{oa} → {nh}/{nd}/{na}")
                print(f"   概率变化: 主{dh:+.1f}%  平{dd:+.1f}%  客{da:+.1f}%")
            for a in alerts:
                print(f"   {a}")
            print()
            signals.append({
                'match_id': mid,
                'home': home_cn, 'away': away_cn, 'league': league,
                'old_spf': f'{oh}/{od}/{oa}' if old_spf else '-',
                'new_spf': f'{nh}/{nd}/{na}' if new_had else '-',
                'changes': spf_changes,
                'alerts': alerts,
                'handicap_change': handicap_change,
            })

    # 4. 更新 daily_tracking.json
    tracking['matches'] = updated_matches
    tracking['afternoon_analysis'] = {
        'checked_at': datetime.now().isoformat(),
        'api_data_available': len(latest),
        'signals_detected': len(signals),
    }
    tracking['afternoon_signals'] = signals

    out_path = ROOT / 'daily_tracking.json'
    json.dump(tracking, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
    print(f"✅ daily_tracking.json 已更新 ({out_path})")

    # 5. 汇总
    print()
    print(f"{'='*60}")
    print(f"═══ 午盘分析完成 ═══")
    print(f"总场次: {tracking['total_matches']}")
    print(f"最新赔率获取: {len(latest)}/{tracking['total_matches']}")
    print(f"出现信号的比赛: {len(signals)}")

    if signals:
        print()
        print("⚠ 重点关注 (赔率变动显著):")
        for s in signals:
            print(f"  {s['match_id']} {s['home']} vs {s['away']} ({s['league']})")
            for a in s['alerts']:
                print(f"    {a}")
    else:
        print()
        print("✅ 所有比赛赔率稳定, 无异常信号")

    return signals

if __name__ == '__main__':
    signals = analyze()
