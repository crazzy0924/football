# -*- coding: utf-8 -*-
"""建立队名总表: 体彩中文名 ↔ SofaScore 名 ↔ 我们的规范名。

用途: 一次性打通三个命名空间, 以后不再出现"识别失败"。
      pipeline 的盘口匹配、result_fetcher 的赛果匹配都可以先查这张表。

用法:
    python tools/build_team_map.py            # 用已有 sofascore_teams.json 重建表
    python tools/build_team_map.py --fetch    # 先走 SofaScore 抓最新球队名单再建表
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from difflib import SequenceMatcher  # noqa: E402

from pipeline.team_names import CN_TO_EN_TEAM, TEAM_STOP, team_score, team_tokens  # noqa: E402


def _fold_plain(s: str) -> str:
    """只留字母数字的折叠形式, 用于字符相似度。"""
    import re as _re
    import unicodedata as _ud
    x = str(s or '')
    for _k, _v in {'ø': 'o', 'Ø': 'o', 'đ': 'd', 'ð': 'd', 'ł': 'l', 'ß': 'ss',
                   'æ': 'ae', 'œ': 'oe', 'þ': 'th', 'ı': 'i', 'ŋ': 'n'}.items():
        x = x.replace(_k, _v)
    x = _ud.normalize('NFKD', x.lower())
    x = ''.join(c for c in x if not _ud.combining(c))
    return _re.sub(r'[^a-z0-9]', '', x)


def char_sim(a: str, b: str) -> float:
    """整名字符相似度 (0~1)。token 并列时的决胜手段。"""
    return SequenceMatcher(None, _fold_plain(a), _fold_plain(b)).ratio()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SF_TEAMS = os.path.join(ROOT, 'data', 'state', 'sofascore_teams.json')
OUT = os.path.join(ROOT, 'data', 'state', 'team_name_map.json')

# SofaScore 联赛 id → 我们的联赛代码 (只做这些)
TOURNAMENTS = [(17, 'PL'), (8, 'PD'), (35, 'BL1'), (23, 'SA'), (34, 'FL1'), (7, 'UCL')]
API = 'https://api.sofascore.com/api/v1'

# 人工订正: SofaScore 名 → 我们的规范名。
# token 匹配搞不定的都在这 —— 要么缩写(Olympique Lyonnais↔Lyon),
# 要么拼写差异(Stade Rennais↔Rennes), 要么我方表里本身是简写/笔误。
# 2026-09-11 建立, 遇到新的识别失败就往这里加一条。
CURATED = {
    # token 并列 + 字符相似度也搞不定的 (Manchester City 会被 "manchester" 带偏到
    # Manchester United FC), 必须手工钉死
    'Manchester City': 'Man City',
    'Manchester United': 'Man United',
    # 马德里双雄: token 集合完全相同(都是 {madrid}), 自动规则分不开, 必须钉死
    'Real Madrid': 'Real Madrid',
    'Real Madrid CF': 'Real Madrid',
    'Atlético Madrid': 'Ath Madrid',
    'Ath Madrid': 'Ath Madrid',
    'Athletic Club': 'Ath Bilbao',
    'Espanyol': 'Espanol',                      # 注: 我方表里 "Espanol" 是拼写错误(应为 Espanyol), 暂按现状对齐
    'Stade Rennais': 'Rennes',
    'Olympique Lyonnais': 'Lyon',
    'Hamburger SV': 'Hamburg',
    'Sporting CP': 'Sporting Clube de Portugal',
    'Olympiacos FC': 'Olympiakos',
    'AEK Athens': '雅典AEK',
    'Fenerbahçe': '费内巴切',
    'Sabah FK': '萨巴赫',
    'LASK': 'LASK Linz',
    'NEC Nijmegen': 'Nijmegen',
    'Viking FK': 'Viking',
    'Mjällby AIF': '米亚尔比',
    'Heart of Midlothian': 'Hearts',
}


def fetch_sofascore_teams() -> dict:
    """抓六项赛事的当前赛季球队名单。"""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel='msedge')
        ctx = b.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/125.0 Safari/537.36'))
        pg = ctx.new_page()
        pg.goto('https://www.sofascore.com/football', timeout=45000, wait_until='domcontentloaded')
        pg.wait_for_timeout(2500)

        def call(u):
            for _ in range(3):
                r = pg.evaluate(
                    """async (u) => { try { const r = await fetch(u, {headers:{'x-requested-with':'XMLHttpRequest'}});
                       if (!r.ok) return {__e: r.status}; return await r.json(); } catch (e) { return {__e: String(e)}; } }""", u)
                if isinstance(r, dict) and '__e' not in r:
                    return r
                import time as _t
                _t.sleep(1.5)
            return {}

        for tid, code in TOURNAMENTS:
            s = call('%s/unique-tournament/%d/seasons' % (API, tid))
            seasons = s.get('seasons') or []
            if not seasons:
                print('  %s: 拿不到赛季' % code)
                continue
            sid = seasons[0]['id']
            t = call('%s/unique-tournament/%d/season/%s/teams' % (API, tid, sid))
            teams = t.get('teams') or []
            out[code] = [{'name': (x.get('team') or x).get('name'),
                          'id': (x.get('team') or x).get('id')} for x in teams]
            print('  %s (赛季 %s): %d 支' % (code, sid, len(out[code])))
        b.close()
    with open(SF_TEAMS, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('已保存 → %s' % SF_TEAMS)
    return out


def load_canonical() -> dict:
    """我们的规范名 → 联赛。优先 team_params(模型在用的确切名字), 再补 team_league。"""
    canon = {}
    mp = os.path.join(ROOT, 'data', 'state', 'team_league.json')
    if os.path.exists(mp):
        for k, v in json.load(open(mp, encoding='utf-8')).items():
            canon[k] = v
    mdir = os.path.join(ROOT, 'data', 'state', 'models')
    for lg in os.listdir(mdir) if os.path.isdir(mdir) else []:
        fp = os.path.join(mdir, lg, 'team_params.json')
        if not os.path.exists(fp):
            continue
        try:
            for k in json.load(open(fp, encoding='utf-8')).keys():
                canon.setdefault(k, lg)
        except Exception:
            pass
    return canon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true', help='先抓 SofaScore 最新球队名单')
    a = ap.parse_args()

    if a.fetch or not os.path.exists(SF_TEAMS):
        print('抓取 SofaScore 球队名单...')
        sf = fetch_sofascore_teams()
    else:
        sf = json.load(open(SF_TEAMS, encoding='utf-8'))
        print('用已有 %s (%d 个联赛)' % (SF_TEAMS, len(sf)))

    canon = load_canonical()
    print('我们的规范名: %d 个' % len(canon))

    # 体彩侧: ID → 中文名/规范名; 中文名 → 英文 (CN_TO_EN_TEAM 反查)
    tid_map = {}
    tp = os.path.join(ROOT, 'data', 'state', 'team_id_map.json')
    if os.path.exists(tp):
        try:
            tid_map = json.load(open(tp, encoding='utf-8'))
        except Exception:
            tid_map = {}
    en_to_cn = {}
    for cn, en in CN_TO_EN_TEAM.items():
        en_to_cn.setdefault(en, cn)
    print('体彩队ID表: %d 条;  中文→英表: %d 条' % (len(tid_map), len(CN_TO_EN_TEAM)))

    rows, unmatched_sf, unmatched_canon = [], [], []
    ambiguous_list = []
    used_canon = set()
    for code, teams in sf.items():
        for t in teams:
            nm = t.get('name') or ''
            # 匹配策略 (2026-09-11): 宁可不匹配, 也不给错匹配。
            # 只用"唯一最高分"判定。并列 = 有歧义 → 标 ambiguous 交人工订正。
            # 反例(都是实测出来的):
            #   Hull City       ↔ Man City / Bristol City   (共享 "city")
            #   Leeds United    ↔ Man United                (共享 "united")
            #   Real Madrid     ↔ Ath Madrid                (共享 "madrid")
            #   AC Sparta Praha ↔ SK Slavia Praha           (共享 "praha")
            # 这类地理/通用词单独出现不足以认定同一支队。
            scored = sorted(((team_score(nm, c), c) for c in canon), key=lambda x: -x[0])
            top = scored[0][0] if scored else 0
            tied = [c for s, c in scored if s == top and s >= 1]
            cur = CURATED.get(nm)
            if cur:
                aliases, primary, ambiguous = [cur], cur, []
            elif top >= 1 and len(tied) == 1:
                aliases, primary, ambiguous = tied, tied[0], []
            elif top >= 1:
                # token 并列 → 用整名字符相似度决胜。
                # Manchester City: {Man City, Manchester United FC, Bristol City} 都只共享 1 个 token,
                #   但 "manchestercity"/"mancity" 的字符相似度明显最高 → 选中 Man City。
                ranked = sorted(tied, key=lambda c: -char_sim(nm, c))
                primary = ranked[0]
                # 同一队在我方规范名里常有"简称/全称"两份 (五大用 Lens, 欧冠用 Racing Club
                # de Lens) —— 把 token 集合是超集的候选也并作别名, 否则两边归不到一起。
                # 加字符相似度 ≥0.7 的前提, 避免 Real Madrid / Ath Madrid 这种
                # token 集合完全相同但队不同的情况被并进来。
                pk = team_tokens(primary)
                aliases = [primary]
                for c in tied:
                    if c == primary:
                        continue
                    ck = team_tokens(c)
                    if pk < ck or ck < pk:
                        # 严格超集 → 确定为同队的简写/全称 (Lens ⊂ Racing Club de Lens)
                        aliases.append(c)
                ambiguous = tied if char_sim(nm, primary) < 0.5 else []
            else:
                # 表里没有的球队也登记为自身, 这样匹配时"两边都能查到"恒成立,
                # 不会掉回模糊匹配 (否则 Manchester City 会因共享 "city" 命中 Bristol City)
                aliases, primary = [nm], nm
                ambiguous = []
            row = {'league': code, 'sofascore': nm, 'sofascore_id': t.get('id'),
                   'canonical': primary, 'canonical_aliases': aliases,
                   'score': team_score(nm, primary) if primary else 0}
            if ambiguous:
                row['ambiguous'] = ambiguous
                ambiguous_list.append({'sofascore': nm, 'candidates': ambiguous})
            if primary:
                used_canon.update(aliases)
                row['league'] = canon.get(primary, code)
                row['sporttery_cn'] = en_to_cn.get(primary) or next(
                    (en_to_cn.get(a) for a in aliases if en_to_cn.get(a)), None)
            else:
                unmatched_sf.append(nm)
            rows.append(row)

    # 体彩 ID → 规范名 也挂上
    for sid, name in (tid_map or {}).items():
        if not isinstance(name, str):
            continue
        for r in rows:
            if r.get('canonical') and team_score(name, r['canonical']) >= 1:
                r['sporttery_id'] = sid
                break

    for c, lg in canon.items():
        if c not in used_canon:
            unmatched_canon.append({'canonical': c, 'league': lg,
                                    'sporttery_cn': en_to_cn.get(c)})

    # ── 赛果/预测里出现过的队名也归入总表 ──────────────────────────
    # 这些是 football-data 与体彩口径的写法 (FC Bayern München / Fenerbahçe SK /
    # Como 1907 ...), 与 SofaScore 名不同, 2026-09-11 的复盘失败正是栽在这里。
    import glob as _glob
    extra: dict = {}
    for pat in ('data/output/results_*.json', 'data/output/predictions_*.json'):
        for fp in _glob.glob(os.path.join(ROOT, pat)):
            try:
                items = json.load(open(fp, encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                for side in ('home_team', 'away_team'):
                    nm = it.get(side)
                    if not nm or nm in extra:
                        continue
                    c = CURATED.get(nm)
                    if not c:
                        # 按"规范名"去重再比: 同一个队可能在 PL 与 UCL 各有一行,
                        # 不去重会让"最高分唯一"的判断失效 (2 > 2 为假) → 选错队。
                        agg: dict = {}
                        for r in rows:
                            if not r.get('canonical'):
                                continue
                            s = team_score(nm, r['sofascore'])
                            if s >= 1:
                                k = r['canonical']
                                # 同时记住"命中它的那个 SofaScore 名", 后面做字符门槛用
                                if k not in agg or s > agg[k][0]:
                                    agg[k] = (s, r['sofascore'])
                        items = sorted(agg.items(), key=lambda kv: -kv[1][0])
                        if items:
                            if len(items) == 1 or items[0][1][0] > items[1][1][0]:
                                pick = items[0][0]
                            else:
                                pick = max((k for k, _ in items), key=lambda cc: char_sim(nm, cc))
                            # 字符门槛要比"命中的 SofaScore 名", 不能比规范名 ——
                            # 2026-09-12: 赛果源会带后缀("Stade Rennais FC 1901"), 而规范名
                            # 是简称("Rennes"), 拿规范名比会因相似度过低被判"认不出",
                            # 于是自登记成自身, 该场永远结算不了。
                            if char_sim(nm, agg[pick][1]) >= 0.6:
                                c = pick
                    if not c and nm in canon:
                        c = nm
                    if not c:
                        # 认不出来就登记为自身, 保证"两边都能查到"恒成立, 不回退模糊
                        c = nm
                    extra[nm] = c
    print('  赛果/预测侧队名: %d 个已归入总表' % len(extra))

    doc = {
        'note': '队名总表: 体彩中文名 <-> SofaScore 名 <-> 我们的规范名',
        'result_names': extra,
        'rows': sorted(rows, key=lambda r: (r.get('league') or '', r.get('canonical') or r['sofascore'])),
        'unmatched_sofascore': unmatched_sf,
        'ambiguous': ambiguous_list,
        'unmatched_canonical': unmatched_canon,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    hit = sum(1 for r in rows if r.get('canonical'))
    with_cn = sum(1 for r in rows if r.get('sporttery_cn'))
    with_id = sum(1 for r in rows if r.get('sporttery_id'))
    print('')
    print('总表: %d 行' % len(rows))
    print('  已对齐我们的规范名 : %d / %d' % (hit, len(rows)))
    print('  有体彩中文名       : %d' % with_cn)
    print('  有体彩队ID         : %d' % with_id)
    print('  SofaScore 侧未对齐 : %d' % len(unmatched_sf))
    print('  有歧义待人工确认   : %d' % len(ambiguous_list))
    print('  规范名侧未出现     : %d' % len(unmatched_canon))
    if ambiguous_list:
        print('')
        print('  歧义明细 (需要往 CURATED 里加一条):')
        for x in ambiguous_list[:25]:
            print('    %-30s 候选: %s' % (x['sofascore'], ' | '.join(x['candidates'][:4])))
    print('已保存 → %s' % OUT)


if __name__ == '__main__':
    main()
