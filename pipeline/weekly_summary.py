# -*- coding: utf-8 -*-
"""
周复盘页生成器 (2026-08-24 新增, 周一重训后自动运行)

整体思路复盘: 逐日趋势 + 四维胜率 + 维度台账 + 本周修正记录 + 下周重点。
输出: data/output/weekly_YYYY-MM-DD.html (历史) + weekly_latest.html (首页常驻链接)
"""
from __future__ import annotations

import glob
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BEIJING = timezone(timedelta(hours=8))

_CSS = """
  :root { --bg:#0b0f1a; --card:#121a2c; --line:#1e2a42; --txt:#e9eef8; --dim:#8d99b0;
          --green:#34d399; --amber:#fbbf24; --blue:#5ea8ff; --red:#f87171; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:radial-gradient(1000px 400px at 20% -10%, rgba(94,168,255,.12), transparent 60%), var(--bg);
         color:var(--txt); min-height:100vh; padding:28px 16px 40px; line-height:1.6; }
  .container { max-width:900px; margin:0 auto; }
  .hero { text-align:center; padding:30px 10px 20px; }
  .badge { display:inline-block; font-size:.8rem; color:#bfd7ff;
           background:linear-gradient(135deg, rgba(94,168,255,.16), rgba(167,139,250,.14));
           border:1px solid rgba(94,168,255,.35); padding:5px 16px; border-radius:999px; }
  .hero h1 { font-size:1.8rem; font-weight:800; margin-top:12px;
             background:linear-gradient(90deg,#e9eef8,#9ec4ff 60%,#c4b5fd);
             -webkit-background-clip:text; background-clip:text; color:transparent; }
  .hero-sub { color:var(--dim); font-size:.85rem; margin-top:8px; }
  .summary { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0 22px; }
  .s-box { background:linear-gradient(180deg,var(--card),#101725); border:1px solid var(--line);
           border-radius:12px; padding:12px 6px; text-align:center; }
  .s-box .v { font-size:1.3rem; font-weight:800; }
  .s-box .l { font-size:.72rem; color:var(--dim); }
  .sec { font-size:.88rem; font-weight:800; letter-spacing:1px; color:#9ec4ff; margin:18px 0 8px; }
  .tb-wrap { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-size:.82rem; min-width:520px; }
  th, td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
  th { color:#a8c7f0; background:#0e1526; font-size:.75rem; }
  .good { color:var(--green); font-weight:700; } .bad { color:var(--red); font-weight:700; }
  .fix { margin:6px 0; background:#0e1526; border:1px solid var(--line); border-radius:10px; padding:10px 14px; font-size:.84rem; }
  .fix b { color:#fcd34d; }
  .footer { text-align:center; color:var(--dim); font-size:.78rem; margin-top:26px; }
  a { color:#38bdf8; text-decoration:none; }
"""


def _agg_four_dim(html: str, dims: dict, focus: dict) -> int:
    """从复盘页聚合四维判定"""
    import re
    n = 0
    for bm in re.findall(r'<article class="match">([\s\S]*?)<\/article>', html):
        n += 1
        lg = (re.search(r"联赛 ([A-Z0-9]+)", bm) or [None, ""])[1] or ""
        is_focus = lg in ("PL", "PD", "BL1", "SA", "FL1")
        for m in re.finditer(r'<span class="verdict-(\w+)">([^<]+)<\/span> <b>([^<]+)<\/b>', bm):
            name, v = m.group(3), m.group(2)
            if name not in dims:
                continue
            if v == "命中":
                dims[name]["h"] += 1
                if is_focus:
                    focus[name]["h"] += 1
            elif v == "未中":
                dims[name]["m"] += 1
                if is_focus:
                    focus[name]["m"] += 1
            elif v == "走盘":
                dims[name]["push"] += 1
                if is_focus:
                    focus[name]["push"] += 1
    return n


def main() -> None:
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    track_path = os.path.join("data", "output", "daily_tracking.json")
    ledger_path = os.path.join("data", "state", "dimension_ledger.json")

    track = json.load(open(track_path, encoding="utf-8"))
    days = [d for d in (track.get("days") or []) if d.get("date", "") >= "2026-08-16"]
    tm = sum(d.get("matches", 0) for d in days)
    tw = sum(d.get("accuracy", 0) * d.get("matches", 0) for d in days)
    tb = sum(d.get("brier", 0) * d.get("matches", 0) for d in days)

    dims = {k: {"h": 0, "m": 0, "push": 0} for k in ("胜平负", "波胆", "大小球", "让球")}
    focus = {k: {"h": 0, "m": 0, "push": 0} for k in dims}
    n_all = 0
    for p in sorted(glob.glob(os.path.join("data", "output", "review_analysis_2026-08-*.html"))):
        with open(p, "r", encoding="utf-8") as f:
            n_all += _agg_four_dim(f.read(), dims, focus)

    ledger = json.load(open(ledger_path, encoding="utf-8")).get("dimensions", {})

    day_rows = "".join(
        f"<tr><td>{d['date']}</td><td>{d.get('matches', 0)}</td>"
        f"<td>{d.get('cold_start_count', 0) or 0}</td>"
        f"<td>{d.get('brier', 0):.4f}</td>"
        f"<td class=\"{'good' if d.get('accuracy', 0) >= 0.5 else 'bad'}\">{d.get('accuracy', 0):.0%}</td></tr>"
        for d in days
    )

    def _rate(v):
        t = v["h"] + v["m"]
        return f"{v['h']}/{t} = {v['h'] / t:.1%}" if t else "n/a"

    dim_rows = "".join(
        f"<tr><td>{k}</td><td>{_rate(v)}</td><td>{_rate(focus[k])}</td></tr>"
        for k, v in dims.items()
    )
    led_rows = "".join(
        f"<tr><td>{k}</td><td>{v.get('n', 0)}</td>"
        f"<td>{v.get('correct', 0) / v.get('n', 1):.1%}</td>"
        f"<td>{v.get('brier_sum', 0) / v.get('n', 1):.4f}</td></tr>"
        for k, v in ledger.items()
    )

    fixes = [
        ("方向融合思路成功", "胜平负 66.7% (五大联赛 68%), 冷启动日靠市场定价也能 75% — 维持现状"),
        ("波胆降级", "精确比分 12.5%: 页面已标注'仅供方向参考', 不再作为信心来源"),
        ("BTTS降权", "52.2%≈抛硬币: 提示词标注'不作独立信号', 页面弱化展示"),
        ("让球盘修复", "edge键名bug已修(此前长赔率虚高), 下周重新观察信号质量"),
        ("赔率变动监控", "≥0.05变动自动注入证据包, 下周验证奈梅亨类漏信号是否复现"),
        ("一致性校验", "方向-比分冲突/BTTS矛盾自动标记, 终盘强制处理"),
    ]
    fix_html = "".join(f'<div class="fix"><b>{a}:</b> {b}</div>' for a, b in fixes)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>周复盘 — {today}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="badge">📈 周整体复盘 · 五大联赛开赛以来</div>
    <h1>第 1 周 (08-16 → 08-23)</h1>
    <div class="hero-sub">逐日趋势 + 四维胜率 + 维度台账 + 修正记录 · 自动生成</div>
  </div>
  <div class="summary">
    <div class="s-box"><div class="v">{tm}</div><div class="l">周场次</div></div>
    <div class="s-box"><div class="v" style="color:#6ee7b7;">{tw / tm:.1%}</div><div class="l">加权准确率</div></div>
    <div class="s-box"><div class="v" style="color:#93c5fd;">{tb / tm:.4f}</div><div class="l">加权Brier</div></div>
    <div class="s-box"><div class="v">{len(days)}</div><div class="l">复盘天数</div></div>
  </div>
  <div class="sec">一 · 逐日趋势</div>
  <div class="tb-wrap"><table>
    <tr><th>日期</th><th>场次</th><th>冷启动</th><th>Brier</th><th>准确率</th></tr>
    {day_rows}
  </table></div>
  <div class="sec">二 · 四维胜率 (全部 vs 仅五大联赛)</div>
  <div class="tb-wrap"><table>
    <tr><th>维度</th><th>全部</th><th>仅五大联赛</th></tr>
    {dim_rows}
  </table></div>
  <div class="sec">三 · 维度台账累计</div>
  <div class="tb-wrap"><table>
    <tr><th>维度</th><th>样本</th><th>命中率</th><th>Brier</th></tr>
    {led_rows}
  </table></div>
  <div class="sec">四 · 本周修正记录 (思路复盘成果)</div>
  {fix_html}
  <div class="footer">自动生成于 {today} · <a href="../index.html">返回首页</a></div>
</div>
</body>
</html>"""
    os.makedirs(os.path.join("data", "output"), exist_ok=True)
    out1 = os.path.join("data", "output", f"weekly_{today}.html")
    out2 = os.path.join("data", "output", "weekly_latest.html")
    for p in (out1, out2):
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
    print(f"[周复盘] 已保存 → {out1} (+ weekly_latest.html)")

    # 推送 (汉化纪律 + 断网自愈)
    rc = subprocess.run([sys.executable, "pre_push_check.py"]).returncode
    if rc != 0:
        print("[周复盘] 汉化检查未通过, 跳过推送")
        return
    subprocess.run(["git", "add", "-A"])
    subprocess.run(["git", "commit", "-m", f"周复盘自动生成: 第1周整体思路复盘与修正记录"])
    rc = subprocess.run(["git", "push", "origin", "master"]).returncode
    if rc != 0:
        try:
            import daily_run
            daily_run._register_push_retry()
        except Exception:
            pass
    else:
        print("[周复盘] 已推送")


if __name__ == "__main__":
    main()
