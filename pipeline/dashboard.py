# -*- coding: utf-8 -*-
"""复盘看板生成器: 聚合每日复盘/维度台账/自检/待办 → data/output/复盘看板.html (2026-09-02 新增)"""
import glob, io, json, os, re, sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BEIJING = timezone(timedelta(hours=8))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join("data", "output")

def _text(fp: str) -> str:
    try:
        with open(fp, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return ""
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw)
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = raw.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", raw)

def _g(rx: str, text: str):
    m = re.search(rx, text)
    return m.group(1) if m else "—"

# 1) 逐日复盘表 (review_*.html)
daily_rows = []
for fp in sorted(glob.glob(os.path.join(OUT_DIR, "review_2026-*.html"))):
    d = os.path.basename(fp)[len("review_"):-len(".html")]
    t = _text(fp)
    matched = _g(r"匹配 (\d+)/(\d+)", t)
    acc = _g(r"(\d+\.\d+)% 准确率", t)
    brier = _g(r"(\d+\.\d+) Brier", t)
    pnl = _g(r"([+-]\d+\.\d+)u 盈亏", t)
    daily_rows.append((d, matched, acc, brier, pnl))

# 队名工具 (先导入, 供对账使用)
try:
    from pipeline.team_names import CN_TO_EN_TEAM
    EN_TO_CN = {v: k for k, v in CN_TO_EN_TEAM.items()}
except Exception:
    EN_TO_CN = {}
try:
    from pipeline.data_loader import normalize_team_name
except Exception:
    def normalize_team_name(n):
        return n

# 2) 英冠首日 (09-01) 对账
elc_rows = []
try:
    results = {f"{m['home_team']}|{m['away_team']}": m for m in json.load(open(os.path.join(OUT_DIR, "results_2026-09-01.json"), encoding="utf-8"))}
except Exception:
    results = {}
try:
    preds = json.load(open(os.path.join(OUT_DIR, "predictions_2026-09-01.json"), encoding="utf-8"))
    pred_map = {(normalize_team_name(p["home_team"]), normalize_team_name(p["away_team"])): p for p in preds if p.get("league_code") == "ELC"}
except Exception:
    pred_map = {}
elc_hit = elc_miss = 0
for rk, rv in results.items():
    h, a = rk.split("|")
    hg, ag = rv.get("home_goals"), rv.get("away_goals")
    if hg is None or ag is None:
        continue
    # 结果对账: 预测概率最高方向 vs 实际
    pm = pred_map.get((normalize_team_name(h), normalize_team_name(a)))
    pick = "—"
    if pm:
        m = pm.get("model") or {}
        ph, pd_, pa = m.get("home_win", 0), m.get("draw", 0), m.get("away_win", 0)
        best = max(ph, pd_, pa)
        pick = "主胜" if best == ph else ("平局" if best == pd_ else "客胜")
    actual = "主胜" if hg > ag else ("平局" if hg == ag else "客胜")
    hit = (pick == actual)
    if pick != "—":
        if hit:
            elc_hit += 1
        else:
            elc_miss += 1
    cn_h = EN_TO_CN.get(normalize_team_name(h), h)
    cn_a = EN_TO_CN.get(normalize_team_name(a), a)
    elc_rows.append((cn_h, cn_a, f"{hg}-{ag}", actual, pick, "命中" if hit else ("未中" if pick != "—" else "—")))

# 3) 周复盘四维+台账 (weekly_latest.html)
wt = _text(os.path.join(OUT_DIR, "weekly_latest.html"))
m4 = re.search(r"胜平负\s+(\d+/\d+ = [\d.]+%).*?波胆\s+(\d+/\d+ = [\d.]+%).*?大小球\s+(\d+/\d+ = [\d.]+%).*?让球\s+(\d+/\d+ = [\d.]+%)", wt)
if m4:
    spf, cs, ou, ah = m4.groups()
else:
    spf = cs = ou = ah = "—"
m_led = re.search(r"1X2\s+(\d+)\s+([\d.]+)%\s+([\d.]+).*?OU25\s+(\d+)\s+([\d.]+)%\s+([\d.]+).*?OU35\s+(\d+)\s+([\d.]+)%\s+([\d.]+).*?BTTS\s+(\d+)\s+([\d.]+)%\s+([\d.]+).*?AH\s+(\d+)\s+([\d.]+)%\s+([\d.]+)", wt)
ledger = list(m_led.groups()) if m_led else None

# 4) 自检 (最新 self_check json)
violations = []
sc_files = sorted(glob.glob(os.path.join(OUT_DIR, "self_check_2026-*.json")))
if sc_files:
    sc = json.load(open(sc_files[-1], encoding="utf-8"))
    for c in sc.get("checks", []):
        if c.get("结果") != "通过":
            violations.append(f"{c['项']} {c['检查']}: {c['详情']}")

# 5) 待办
todos = [
    ("P1", "09-01 复盘漏配西汉姆vs狼队 (全名 West Ham United FC 未匹配): 结果 4-2 主胜, 客胜信号未中, 注单未结算"),
    ("P1", "08-30 复盘缺口: 只匹配 5/13 场, 8 场凌晨场待补"),
    ("P2", "周报区间标签滞后: 标题写 08-16→08-23, 数据实至 08-29"),
    ("P2", "英冠首日冲突率 6/8 偏高, 模型 3 轮样本噪音大, 下周重训后再评估"),
]

now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")

# 渲染
daily_html = "".join(
    f"<tr><td>{d}</td><td>{m}</td><td>{a}</td><td>{b}</td><td>{p}</td></tr>"
    for d, m, a, b, p in daily_rows
)
elc_html = "".join(
    f"<tr><td>{h} vs {a2}</td><td>{sc}</td><td>{act}</td><td>{pk}</td><td style='color:{'#34d399' if st=='命中' else ('#f87171' if st=='未中' else '#8d99b0')}'>{st}</td></tr>"
    for h, a2, sc, act, pk, st in elc_rows
)
viol_html = "".join(f"<li>{v}</li>" for v in violations) if violations else "<li>全部通过</li>"
todo_html = "".join(f"<li><b>[{lv}]</b> {tx}</li>" for lv, tx in todos)
ledger_html = ""
if ledger:
    n, hr, br = ledger[0], ledger[1], ledger[2]
    ledger_html = f"<tr><td>1X2</td><td>{n}</td><td>{hr}%</td><td>{br}</td></tr>"
    for i, name in ((3, "OU25"), (6, "OU35"), (9, "BTTS"), (12, "AH")):
        if i + 2 < len(ledger):
            ledger_html += f"<tr><td>{name}</td><td>{ledger[i]}</td><td>{ledger[i+1]}%</td><td>{ledger[i+2]}</td></tr>"

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>复盘看板 · 足球大模型</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;background:radial-gradient(900px 400px at 20% -10%,rgba(94,168,255,.12),transparent 60%),#0b0f1a;color:#e9eef8;margin:0;padding:28px 16px 48px;line-height:1.6}}
.wrap{{max-width:960px;margin:0 auto}} h1{{font-size:1.7rem;margin:8px 0 2px}} .sub{{color:#8d99b0;font-size:.85rem;margin-bottom:18px}}
.card{{background:#121a2c;border:1px solid #1e2a42;border-radius:12px;padding:16px 18px;margin:14px 0}}
h2{{font-size:1.05rem;color:#9ec4ff;margin:0 0 10px;border-bottom:1px solid #1e2a42;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}} th,td{{padding:6px 8px;border-bottom:1px solid #1e2a42;text-align:left}}
th{{color:#8d99b0;font-weight:600}} .kpi{{display:flex;flex-wrap:wrap;gap:10px}} .k{{flex:1;min-width:120px;background:#0f172a;border:1px solid #1e2a42;border-radius:10px;padding:12px}}
.k b{{display:block;font-size:1.25rem;color:#34d399}} .k span{{color:#8d99b0;font-size:.75rem}}
.warn{{color:#fbbf24}} .bad{{color:#f87171}} .ok{{color:#34d399}} ul{{margin:6px 0;padding-left:20px}} li{{margin:5px 0;font-size:.88rem}}
a{{color:#5ea8ff;text-decoration:none}} .foot{{color:#64748b;font-size:.78rem;text-align:center;margin-top:22px}}
</style></head><body><div class="wrap">
<h1>📊 复盘看板</h1>
<div class="sub">生成于 {now} 北京时间 · 数据来源: 每日复盘/维度台账/自检 · <a href="../index.html">返回首页</a></div>

<div class="card"><h2>最近复盘 — 2026-09-01 (英冠首日)</h2>
<div class="kpi">
<div class="k"><span>审计场次</span><b>{daily_rows[-1][1] if daily_rows else "—"}</b></div>
<div class="k"><span>准确率</span><b>{daily_rows[-1][2] if daily_rows else "—"}</b></div>
<div class="k"><span>Brier</span><b>{daily_rows[-1][3] if daily_rows else "—"}</b></div>
<div class="k"><span>盈亏</span><b>{daily_rows[-1][4] if daily_rows else "—"}</b></div>
</div>
<p style="font-size:.85rem;color:#8d99b0;margin:10px 0 0">方向分解: 主胜 3/3 (100%) · 平局 0/2 · 客胜 0/2 — 客胜方向全军覆没, 含昨晚唯一英冠注单(西汉姆客胜)实际 4-2 主胜未中; 大2.5 极端信号(模型92%)命中 6 球。</p>
</div>

<div class="card"><h2>英冠首日逐场对账 (09-01)</h2>
<table><tr><th>对阵</th><th>赛果</th><th>实际方向</th><th>预测方向</th><th>判定</th></tr>{elc_html}</table>
<p style="font-size:.8rem;color:#8d99b0;margin:8px 0 0">注: 西汉姆vs狼队未进复盘(队名全称匹配失败), 此处以结果文件补录; 系统投注单未记(建议¥20未落地), P&amp;L 账本显示"今日无投注单"。</p>
</div>

<div class="card"><h2>逐日复盘趋势</h2>
<table><tr><th>日期</th><th>匹配</th><th>准确率</th><th>Brier</th><th>盈亏(u)</th></tr>{daily_html}</table>
</div>

<div class="card"><h2>四维胜率 (周复盘口径)</h2>
<table><tr><th>维度</th><th>胜率</th></tr>
<tr><td>胜平负</td><td>{spf}</td></tr><tr><td>波胆</td><td>{cs}</td></tr><tr><td>大小球</td><td>{ou}</td></tr><tr><td>让球</td><td>{ah}</td></tr></table>
</div>

<div class="card"><h2>维度台账 (累计)</h2>
<table><tr><th>维度</th><th>样本</th><th>命中率</th><th>Brier</th></tr>{ledger_html}</table>
</div>

<div class="card"><h2>自检健康 (最新)</h2><ul>{viol_html}</ul></div>

<div class="card"><h2>待办 (P0/P1/P2)</h2><ul>{todo_html}</ul></div>

<div class="foot">足球大模型 · 复盘看板 · 自动生成</div>
</div></body></html>"""

out_path = os.path.join(OUT_DIR, "复盘看板.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print("[看板] 已保存 → " + out_path)
print("[看板] 逐日行数:", len(daily_rows), " 英冠行数:", len(elc_rows), " 自检违规:", len(violations))
