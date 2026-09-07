# -*- coding: utf-8 -*-
"""透明哈希链账本 (借鉴 tactix.football 的 hash-chained pre-commitment)."""
from __future__ import annotations
import hashlib, json, os, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEDGER_PATH = os.path.join('data', 'output', 'transparency_ledger.json')
PAGE_PATH = os.path.join('data', 'output', 'transparency.html')
GENESIS = '0' * 64

def _load():
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def _save(entries):
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

def _picks_summary(predictions):
    out = []
    for p in predictions:
        v = p.get('value') or {}
        m = p.get('model') or {}
        edges = [(v.get('home_edge') or 0), (v.get('draw_edge') or 0), (v.get('away_edge') or 0)]
        out.append({
            'match': (p.get('home_team') or '?') + ' vs ' + (p.get('away_team') or '?'),
            'league': p.get('league_code', ''),
            'probs': [round(m.get('home_win', 0), 4), round(m.get('draw', 0), 4), round(m.get('away_win', 0), 4)],
            'edge': round(max(edges), 4),
            'kelly': round(v.get('kelly', 0) or 0, 4),
            'pick': p.get('bet_pick') or '观望',
        })
    return out

def freeze(date_str, predictions):
    try:
        entries = _load()
        prev = entries[-1]['hash'] if entries else GENESIS
        picks = _picks_summary(predictions)
        created = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        payload = json.dumps({'date': date_str, 'picks': picks}, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256((prev + payload).encode('utf-8')).hexdigest()
        entries.append({'date': date_str, 'created_at': created, 'prev_hash': prev, 'hash': h, 'n_picks': len(picks), 'picks': picks, 'settled': False, 'results': []})
        _save(entries)
        return h
    except Exception as e:
        print('[透明账本] 冻结失败: %s' % e)
        return None

def settle(date_str, results):
    try:
        entries = _load()
        for ent in entries:
            if ent.get('date') == date_str and not ent.get('settled'):
                ent['settled'] = True
                ent['results'] = results
                _save(entries)
                return True
    except Exception as e:
        print('[透明账本] 结算失败: %s' % e)
    return False

def generate_page():
    entries = _load()
    rows = []
    verified = True
    for ent in entries:
        prev = ent.get('prev_hash', GENESIS)
        payload = json.dumps({'date': ent.get('date'), 'picks': ent.get('picks', [])}, sort_keys=True, ensure_ascii=False)
        expect = hashlib.sha256((prev + payload).encode('utf-8')).hexdigest()
        ok = (ent.get('hash', '') == expect)
        if not ok:
            verified = False
        settled = ent.get('settled', False)
        pick_rows = ''.join(
            '<tr><td>%s</td><td class=dim>%s</td><td>%.0f%%/%.0f%%/%.0f%%</td><td class=%s>%+.1f%%</td><td>%s</td></tr>' % (
                p['match'], p['league'], p['probs'][0]*100, p['probs'][1]*100, p['probs'][2]*100,
                ('hit' if (p['edge'] or 0) >= 0.05 else 'dim'), (p['edge'] or 0)*100, p['pick'])
            for p in ent.get('picks', [])
        )
        res_rows = ''.join('<tr><td>%s %s-%s %s</td></tr>' % (r.get('home_team','?'), r.get('home_goals','-'), r.get('away_goals','-'), r.get('away_team','?')) for r in ent.get('results', []))
        mark = '✓ 链验证通过' if ok else '✗ 链断裂'
        cls = 'ok' if ok else 'bad'
        st = '已结算' if settled else '待结算'
        rows.append('<div class=entry><div class=e-head><b>%s</b><span class=%s>%s</span><span class=dim>%s · %d 场 · %s</span></div><div class=hash>%s</div><table>%s%s</table></div>' % (
            ent['date'], cls, mark, ent.get('created_at',''), ent.get('n_picks',0), st, ent.get('hash','')[:32], pick_rows, res_rows))
    css = ':root{--bg:#0a1929;--card:#0f2037;--line:#1d3049;--txt:#eef2ff;--dim:#8896b3;--teal:#00d4a8;--red:#f2877e}*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,PingFang SC,Microsoft YaHei,sans-serif;background:linear-gradient(135deg,#0a1929 0%,#132a45 55%,#0e2036 100%);color:var(--txt);min-height:100vh;padding:32px 16px 48px;line-height:1.6}.wrap{max-width:880px;margin:0 auto}h1{font-size:1.7rem;margin:6px 0 4px}.sub{color:var(--dim);font-size:.85rem;margin-bottom:22px}.entry{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:14px 0}.e-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:.9rem}.ok{color:var(--teal);font-weight:700}.bad{color:var(--red);font-weight:700}.dim{color:var(--dim)}.hash{font-family:ui-monospace,Consolas,monospace;font-size:.72rem;color:var(--dim);margin:6px 0;word-break:break-all}table{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:8px}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}.hit{color:var(--teal);font-weight:700}.foot{text-align:center;color:var(--dim);font-size:.75rem;margin-top:26px}a{color:#6ea8fe;text-decoration:none}'
    body = ''.join(rows) if rows else '<p class=dim>账本为空，终盘冻结后自动生成。</p>'
    vcolor = '#00d4a8' if verified else '#f2877e'
    vtext = '✓ 全部通过' if verified else '✗ 存在断裂'
    html = '<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>透明账本 · 哈希链存证</title><style>' + css + '</style></head><body><div class=wrap><h1>透明账本 · 哈希链存证</h1><div class=sub>每场预测赛前冻结、赛后结算，写入 append-only 哈希链；篡改任一条会破坏整条链。错过不隐藏，概率不是确定性。18+ 理性投注。</div><div class=sub style="color:' + vcolor + '">整体链验证：' + vtext + '</div>' + body + '<div class=foot>足球预测模型 · 透明存证 · 不构成投注建议 · <a href=index.html>返回首页</a></div></div></body></html>'
    os.makedirs(os.path.dirname(PAGE_PATH), exist_ok=True)
    with open(PAGE_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    return PAGE_PATH

def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'page':
        print('已生成 → ' + generate_page())
    else:
        print('用法: python pipeline/transparency.py page')

if __name__ == '__main__':
    main()