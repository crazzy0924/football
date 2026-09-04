# -*- coding: utf-8 -*-
"""
七维分析存档页生成器 (2026-08-16 新增)

目的: 早盘/午盘把 LLM 七维分析单独存档到网页, 与终盘预测分离:
  - 早盘 09:00 → analysis_morning_YYYY-MM-DD.html (只做七维分析, 不出下注建议)
  - 午盘 18:00 → analysis_midday_YYYY-MM-DD.html (最新赔率重跑七维分析)
  - 终盘 22:00 → predictions_YYYY-MM-DD.html (唯一出预测的页面, 引用早午盘存档)
终盘 LLM 会把早午盘存档注入上下文 (见 analyst.batch_analyze prior_notes),
保证"早盘分析 → 午盘分析 → 终盘预测"全程可追溯。

用法:
  python pipeline/analysis_page.py <日期YYYY-MM-DD> <morning|midday>
  (读取 predictions_<日期>.json + analysis_notes_<阶段>_<日期>.json 重渲染)
"""
from __future__ import annotations

import html as _html
import json
import os
import re as _re
import sys

# 直接以脚本方式运行时 (python pipeline/analysis_page.py) 也能找到项目根目录
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import FOCUS_LEAGUES
except Exception:
    FOCUS_LEAGUES = {"PL", "PD", "BL1", "SA", "FL1"}

STAGE_CN = {"morning": "早盘", "midday": "午盘"}

_CSS = """
  :root { --bg:#0b0f1a; --card:#121a2c; --line:#1e2a42; --txt:#e9eef8; --dim:#8d99b0;
          --green:#34d399; --amber:#fbbf24; --blue:#5ea8ff; --violet:#a78bfa; --red:#f87171; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:radial-gradient(1000px 400px at 20% -10%, rgba(94,168,255,.12), transparent 60%), var(--bg);
         color:var(--txt); min-height:100vh; padding:28px 16px 40px; line-height:1.55; }
  .container { max-width:860px; margin:0 auto; }
  .hero { text-align:center; padding:30px 10px 20px; }
  .badge { display:inline-block; font-size:.8rem; color:#bfd7ff;
           background:linear-gradient(135deg, rgba(94,168,255,.16), rgba(167,139,250,.14));
           border:1px solid rgba(94,168,255,.35); padding:5px 16px; border-radius:999px; }
  .hero h1 { font-size:1.9rem; font-weight:800; margin-top:12px;
             background:linear-gradient(90deg,#e9eef8,#9ec4ff 60%,#c4b5fd);
             -webkit-background-clip:text; background-clip:text; color:transparent; }
  .hero-sub { color:var(--dim); font-size:.85rem; margin-top:8px; }
  .note-strip { text-align:center; background:rgba(251,191,36,.08); border:1px solid rgba(251,191,36,.3);
                color:var(--amber); border-radius:10px; padding:10px 16px; font-size:.85rem; margin:10px 0 22px; }
  .match { background:linear-gradient(180deg, var(--card), #101725); border:1px solid var(--line);
           border-radius:14px; padding:18px; margin:14px 0; }
  .m-head { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; }
  .m-teams { font-size:1.15rem; font-weight:800; }
  .m-league { display:inline-block; background:#233150; border-radius:6px; padding:1px 10px;
              font-size:.75rem; color:#a8c7f0; margin-right:8px; font-weight:600; }
  .tvs { color:var(--dim); font-weight:400; margin:0 8px; }
  .m-meta { color:var(--dim); font-size:.8rem; }
  .pick-line { margin-top:10px; background:rgba(52,211,153,.10); border:1px solid rgba(52,211,153,.35);
               border-radius:10px; padding:8px 14px; font-size:.95rem; color:#6ee7b7; }
  .pick-line b { font-size:1.05rem; }
  .flags-line { margin-top:6px; font-size:.78rem; color:#fcd34d; background:rgba(251,191,36,.08); border-radius:8px; padding:5px 10px; }
  .ds-strip { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
  .ds { font-size:.75rem; padding:3px 10px; border-radius:999px; border:1px solid var(--line); }
  .ds.pos { color:#6ee7b7; background:rgba(52,211,153,.10); border-color:rgba(52,211,153,.3); }
  .ds.neg { color:#fbbf24; background:rgba(251,191,36,.10); border-color:rgba(251,191,36,.3); }
  .ds.zero { color:#8d99b0; }
  .dims { margin-top:12px; display:grid; gap:8px; }
  .dim { background:#0e1526; border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
  .dim-label { font-size:.78rem; font-weight:800; letter-spacing:1px; }
  .dim-body { font-size:.88rem; color:#c6d0e0; margin-top:4px; white-space:pre-wrap; }
  .dim-1 .dim-label { color:var(--blue); }
  .dim-2 .dim-label { color:var(--violet); }
  .dim-3 .dim-label { color:var(--red); }
  .dim-4 .dim-label { color:var(--amber); }
  .dim-5 .dim-label { color:#7dd3fc; }
  .dim-6 .dim-label { color:#f9a8d4; }
  .dim-7 .dim-label { color:var(--green); }
  .model-box { margin-top:12px; background:#0a1120; border:1px dashed #2c3c5c; border-radius:10px;
               padding:10px 14px; font-size:.82rem; color:var(--dim); }
  .model-box b { color:#a8c7f0; }
  .cold { color:var(--amber); font-weight:700; }
  .intel-box { margin-top:10px; background:#0a1120; border:1px solid var(--line); border-radius:10px;
               max-height:220px; overflow:auto; padding:10px 14px; font-size:.8rem; color:var(--dim); white-space:pre-wrap; }
  .footer { text-align:center; color:var(--dim); font-size:.78rem; margin-top:26px; }
  a { color:#38bdf8; text-decoration:none; }
"""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


_URL_RE = _re.compile(r"https?://\S+")
# 连续2个以上纯英文单词 (域名/俱乐部英文名等, 汉化纪律会拦)
_LATIN_RUN_RE = _re.compile(r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*)+")
# 单个域名残留 (sohu.com 之类, 清理干净)
_DOMAIN_TOKEN_RE = _re.compile(r"\b[a-zA-Z0-9\-]+\.(?:com|cn|net|org|io|co|tv|cc|me|xyz|top)\b", _re.IGNORECASE)


def _sanitize_intel(text: str) -> str:
    """清洗情报文本: 去网址/英文词组, 保留中文内容 (汉化纪律 + 页面整洁)"""
    out = []
    for line in (text or "").splitlines():
        line = _URL_RE.sub("", line)
        line = _LATIN_RUN_RE.sub("", line)
        line = _DOMAIN_TOKEN_RE.sub("", line)
        line = line.replace("&ensp;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
        line = _re.sub(r"\s{2,}", " ", line).strip(" -·\t")
        if line.strip():
            out.append(line)
    return "\n".join(out)


def _cn(name: str) -> str:
    """英文队名转中文 (与 reporter 同源)"""
    try:
        from pipeline.reporter import TEAM_CN
        return TEAM_CN.get(name, name)
    except Exception:
        return name


def _zone_label(pos) -> str:
    """积分榜分区 → 战意参考"""
    if pos is None:
        return ""
    if pos <= 3:
        return "争冠区"
    if pos <= 6:
        return "欧战区"
    if pos >= 15:
        return "保级区"
    return "中游"


def _load_market_map(date_str: str) -> dict:
    """加载 data/today.json 的市场盘口 (亚盘/大小/波胆等原始赔率)"""
    try:
        with open(os.path.join("data", "today.json"), "r", encoding="utf-8") as f:
            matches = json.load(f)
    except Exception:
        return {}
    out = {}
    for m in matches:
        key = (m.get("home_team"), m.get("away_team"))
        out[key] = m
    return out


def _load_odds_movement(date_str: str) -> dict:
    """当日赔率快照 → 主胜赔率变动 (早盘→最新)"""
    try:
        from pipeline.reporter import _load_odds_movement as _mov
        return _mov(date_str)
    except Exception:
        return {}


def _build_market_dim(p, market, move) -> str:
    lines = []
    odds = market.get("odds") or {}
    if odds:
        lines.append(
            f"欧赔: 主{odds.get('home'):.2f} / 平{odds.get('draw'):.2f} / 客{odds.get('away'):.2f}"
        )
    if move:
        lines.append(
            f"主胜赔率变动: {move['from']:.2f} → {move['to']:.2f} ({move['delta']:+.2f})"
        )
    ah = market.get("ah_odds") or {}
    if ah and market.get("handicap") is not None:
        lines.append(
            f"亚盘(主{'让' if market['handicap'] >= 0 else '受'}{abs(market['handicap'])}球): "
            f"主{ah.get('home')} / 平{ah.get('draw')} / 客{ah.get('away')}"
        )
    ou = market.get("ou_line")
    if ou and market.get("over_odds") and market.get("under_odds"):
        lines.append(
            f"大小球 {ou} 球: 大{market['over_odds']} / 小{market['under_odds']}"
        )
    cs = market.get("correct_score_odds") or {}
    if cs:
        top = sorted(cs.items(), key=lambda x: x[1])[:3]
        lines.append("波胆最低赔: " + " / ".join(f"{k}@{v}" for k, v in top))
    ah_v = p.get("ah_handicap") or {}
    if ah_v and ah_v.get("edge") and ah_v["edge"].get("best_pick"):
        e = ah_v["edge"]
        lines.append(
            f"模型亚盘倾向: {e['best_pick']} (价值 {e['edge']:+.1%}, 信心 {e.get('confidence', '-')})"
        )
    ou_v = p.get("ou_value")
    if ou_v:
        lines.append(
            f"模型大小球倾向: {ou_v['side']} (模型{ou_v['model']:.0%} vs 市场{ou_v['market']:.0%})"
        )
    return "\n".join(lines) if lines else "无市场数据"


def _build_schedule_dim(p) -> str:
    s = p.get("schedule") or {}
    h7 = s.get("home_7d", 0)
    a7 = s.get("away_7d", 0)
    if not h7 and not a7:
        return "近7天双方均无比赛记录 (新赛季开局/数据未覆盖)"
    return f"近7天场次 — 主队 {h7} 场 / 客队 {a7} 场"


def _build_motivation_dim(p) -> str:
    std = p.get("standings") or {}
    sh = std.get("home")
    sa = std.get("away")
    parts = []
    if sh:
        z = _zone_label(sh.get("pos"))
        parts.append(f"主队: 第{sh.get('pos')}名 ({z})")
    if sa:
        z = _zone_label(sa.get("pos"))
        parts.append(f"客队: 第{sa.get('pos')}名 ({z})")
    return " · ".join(parts) if parts else "积分榜暂无数据 (赛季初)"


def _build_weather_dim(intel_text: str) -> str:
    if not intel_text:
        return "情报未提及天气, 默认正常"
    kws = ["天气", "降雨", "雨", "雪", "大风", "风", "高温", "低温", "湿度"]
    for kw in kws:
        idx = intel_text.find(kw)
        if idx >= 0:
            seg = intel_text[max(0, idx - 15): idx + 40].strip()
            return "情报片段: " + seg.replace("\n", " ")
    return "情报未提及天气, 默认正常"


def _build_h2h_dim(p) -> str:
    h = p.get("h2h_recent")
    if not h:
        return "近3年无交锋记录"
    return (f"近3年交锋: 主队 {h.get('w', 0)}胜 {h.get('d', 0)}平 {h.get('l', 0)}负, "
            f"进球 {h.get('gf', 0)}:{h.get('ga', 0)} (需结合双方阵容变化程度解读: 阵容稳定则参考价值高)")


def _split_note(note: str) -> dict:
    """把 LLM 输出拆成结构段 (八维新版5行格式 + 自检, 兼容旧版定性评估格式)"""
    parts = {"方向分": "", "维度分": "", "结论": "", "关键维度": "", "三条路径": "", "反向验证": "", "触发器": "", "自检": ""}
    if not note:
        return parts
    cur = "结论"
    labels = ["方向分", "维度分", "结论", "关键维度", "三条路径", "反向验证", "触发器", "自检"]
    for line in note.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("定性评估"):  # 旧版格式兼容
            cur = "结论"
            rest = line[len("定性评估"):].lstrip(":： ").strip()
        else:
            rest = None
            for lab in labels:
                if line.startswith(lab):
                    cur = lab
                    rest = line[len(lab):].lstrip(":： ").strip()
                    break
            if rest is None:
                rest = line
        if rest:
            parts[cur] = (parts[cur] + "\n" + rest).strip() if parts[cur] else rest
    return parts


def _dim_strip_html(txt: str) -> str:
    """把 维度分: 市场+1/状态+2/... 渲染成可视化胶囊条 (借鉴八维评分总表)"""
    if not txt:
        return ""
    cells = []
    for lab in ("市场", "状态", "阵容", "交锋", "赛程", "天气", "裁判", "战意"):
        m = _re.search(lab + r"\s*([+-]?\d+(?:\.\d+)?)", txt)
        if not m:
            continue
        val = float(m.group(1))
        cls = "pos" if val > 0 else ("neg" if val < 0 else "zero")
        sign = ("+" if val > 0 else "") + f"{val:g}"
        cells.append(f'<span class="ds {cls}">{_esc(lab)} {sign}</span>')
    return '<div class="ds-strip">' + "".join(cells) + "</div>" if cells else ""


def _build_match_card(p, market, move, note, intel_text) -> str:
    home_en = p.get("home_team", "?")
    away_en = p.get("away_team", "?")
    home_cn = _cn(home_en)
    away_cn = _cn(away_en)
    kick = (market or {}).get("kickoff_time", "")
    league = (market or {}).get("league_name", "") or p.get("league_code", "")
    # 非五大联赛标记 (模型覆盖弱, 市场定价为主)
    if p.get("league_code") not in FOCUS_LEAGUES:
        league = league + (" · 英冠" if p.get("league_code") == "ELC" else " · 非五大")

    cold = p.get("cold_start", False)
    cross_lg = p.get("cross_league", False)
    if cold:
        cold_html = '<span class="cold"> [冷启动 — 模型参数滞后, 分析谨慎参考]</span>'
    elif cross_lg:
        cold_html = '<span class="cold"> [跨级先验 — 次级联赛数据已降权, 谨慎参考]</span>'
    else:
        cold_html = ""

    segs = _split_note(note or "")
    if not segs["结论"] and not segs["方向分"] and not segs["关键维度"]:
        segs["结论"] = note or "暂无定性评估"
    dim7_lines = []
    if segs["方向分"]:
        dim7_lines.append("方向分: " + segs["方向分"])
    dim7_lines.append("结论: " + (segs["结论"] or "暂无"))
    if segs["关键维度"]:
        dim7_lines.append("关键维度: " + segs["关键维度"])
    if segs["三条路径"]:
        dim7_lines.append("三条路径: " + segs["三条路径"])
    dim7_lines.append("反向验证: " + (segs["反向验证"] or "暂无"))
    dim_strip = _dim_strip_html(segs.get("维度分", ""))
    if segs["触发器"]:
        dim7_lines.append("触发器: " + segs["触发器"])
    if segs["自检"]:
        dim7_lines.append("自检: " + segs["自检"])
    dim7_txt = "<br><br>".join(_esc(x) for x in dim7_lines)

    # 模型参考块 (只作存档对比, 非投注建议)
    m = p.get("model", {})
    bayes = p.get("bayesian") or {}
    model_lines = [
        f"模型概率: 主{m.get('home_win', 0):.1%} 平{m.get('draw', 0):.1%} 客{m.get('away_win', 0):.1%}",
        f"预期进球: {m.get('lambda_home', 0):.2f} - {m.get('lambda_away', 0):.2f}",
        f"大2.5: {m.get('over_25', 0):.1%} | BTTS: {m.get('btts', 0):.1%}",
    ]
    if bayes.get("posterior"):
        post = bayes["posterior"]
        model_lines.append(
            f"贝叶斯后验: 主{post.get('home', 0):.1%} 平{post.get('draw', 0):.1%} 客{post.get('away', 0):.1%}"
        )
        mw = bayes.get("model_weight")
        if mw is not None:
            model_lines.append(
                f"市场融合权重: 模型 {mw:.0%} / 市场 {bayes.get('market_weight', 1 - mw):.0%}"
            )

    # 最可能结果标记 (用户要求: 分析页也要把最可能预测标出来, 供参考)
    # 无胜平负赔率的场次: 有让球盘时按规则13由让球盘反推锚点, 完全无盘才"无法预测"
    odds_here = p.get("odds") or {}
    league_code_here = p.get("league_code", "")
    if not odds_here.get("home"):
        if p.get("anchor_from_ah") or ((p.get("ah_handicap") or {}).get("edge") is not None):
            pick_html = '<div class="pick-line">🎯 最可能: <b>锚点反推</b> (体彩未开胜平负盘, 由让球盘反推方向·仅参考)</div>'
        else:
            pick_html = '<div class="pick-line">🎯 最可能: <b>无法预测</b> (体彩未开任何盘口)</div>'
    else:
        if bayes.get("posterior"):
            post = bayes["posterior"]
            prob_triple = (post.get("home", 0), post.get("draw", 0), post.get("away", 0))
        else:
            prob_triple = (m.get("home_win", 0), m.get("draw", 0), m.get("away_win", 0))
        labels = ("主胜", "平局", "客胜")
        best_i = max(range(3), key=lambda i: prob_triple[i])
        top_score_txt = ""
        sd = m.get("score_distribution") or {}
        jt = p.get("joint_top_scores") or []
        if jt:
            # 联合约束比分 (与让球盘/大小球倾向自洽)
            top_score_txt = f" · 最可能比分 {jt[0]['score']} ({jt[0]['prob']:.0%})"
            if sd:
                raw_best = max(sd.items(), key=lambda kv: kv[1])
                if raw_best[0] != jt[0]["score"]:
                    top_score_txt += f" [原始{raw_best[0]}与让球/大小球矛盾, 已按约束修正]"
        elif sd:
            best_score = max(sd.items(), key=lambda kv: kv[1])
            top_score_txt = f" · 最可能比分 {best_score[0]} ({best_score[1]:.0%})"
        cold_tag = " (冷启动·参考)" if p.get("cold_start") else (" (跨级先验·参考)" if p.get("cross_league") else "")
        if p.get("anchor_from_ah"):
            cold_tag += " (市场锚点=让球盘反推)"
        if league_code_here not in ("PL", "PD", "BL1", "SA", "FL1"):
            cold_tag += (" (英冠·仅观察)" if league_code_here == "ELC" else " (非五大·仅观察)")
        pick_html = (f'<div class="pick-line">🎯 最可能: <b>{_esc(labels[best_i])}</b> '
                     f'({prob_triple[best_i]:.1%}){_esc(top_score_txt)}{_esc(cold_tag)}</div>')

    # 一致性预警展示 (复盘经验库规则6/8)
    flags_txt = " · ".join((p.get("flags") or {}).values())
    flags_html = f'<div class="flags-line">⚠️ 一致性预警: {_esc(flags_txt)}</div>' if flags_txt else ""

    market_txt = _build_market_dim(p, market, move)
    intel_html = ""
    if intel_text:
        intel_html = (f'<div class="intel-box"><b style="color:#8d99b0;">证据账本 · 赛前情报 (带来源与日期)</b>\n{_esc(intel_text)}</div>')

    return f"""
<article class="match">
  <header class="m-head">
    <div class="m-teams">
      <span class="m-league">{_esc(league)}</span>{_esc(home_cn)}<span class="tvs">VS</span>{_esc(away_cn)}
      <span style="font-size:.75rem;color:#8d99b0;">({_esc(home_en)} vs {_esc(away_en)})</span>
    </div>
    <span class="m-meta">开球 {_esc(kick) or '时间未定'}{cold_html}</span>
  </header>
  {pick_html}
  {flags_html}
  {dim_strip}
  <div class="dims">
    <div class="dim dim-1"><div class="dim-label">① 市场视角</div><div class="dim-body">{_esc(market_txt)}</div></div>
    <div class="dim dim-2"><div class="dim-label">② 赛程与体能</div><div class="dim-body">{_esc(_build_schedule_dim(p))}</div></div>
    <div class="dim dim-3"><div class="dim-label">③ 伤停与停赛</div><div class="dim-body">见下方"赛前情报原始存档"(Bing自动侦察)</div></div>
    <div class="dim dim-4"><div class="dim-label">④ 战意动机</div><div class="dim-body">{_esc(_build_motivation_dim(p))}</div></div>
    <div class="dim dim-5"><div class="dim-label">⑤ 天气与场地</div><div class="dim-body">{_esc(_build_weather_dim(intel_text))}</div></div>
    <div class="dim dim-6"><div class="dim-label">⑥ 历史交锋(近3年)</div><div class="dim-body">{_esc(_build_h2h_dim(p))}</div></div>
    <div class="dim dim-7"><div class="dim-label">⑦ 八维结论 + 反向验证 + 自检</div><div class="dim-body">{dim7_txt}</div></div>
  </div>
  <div class="model-box"><b>模型存档参考</b> (仅供终盘对比追溯, 非投注建议)<br>{_esc('<br>'.join(model_lines))}</div>
  {intel_html}
</article>"""


def generate_analysis_page(
    date_str: str,
    stage: str,
    predictions: list[dict],
    analyst_notes: dict[str, str] | None,
    intel_text: str = "",
) -> str:
    """生成七维分析存档页, 返回文件路径"""
    stage_cn = STAGE_CN.get(stage, stage)
    market_map = _load_market_map(date_str)
    movement = _load_odds_movement(date_str)
    notes = analyst_notes or {}
    intel_text = _sanitize_intel(intel_text)

    cards = []
    for p in predictions:
        key = (p.get("home_team"), p.get("away_team"))
        market = market_map.get(key, {})
        move = movement.get(key)
        note = notes.get(f"{p.get('home_team')} vs {p.get('away_team')}", "")
        cards.append(_build_match_card(p, market, move, note, intel_text))

    stage_banner = "早盘" if stage == "morning" else "午盘"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{stage_banner}七维分析存档 — {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="badge">🔍 {stage_banner}七维分析存档 · 非预测页</div>
    <h1>{date_str}</h1>
    <div class="hero-sub">聚焦五大联赛 · Dixon-Coles + ELO + 贝叶斯市场融合</div>
  </div>
  <div class="note-strip">本页只做七维分析存档 (数据可追溯), 不出预测、不下注建议。<br>
    终盘预测见 <a href="predictions_{date_str}.html">predictions_{date_str}.html</a> (22:00 生成)</div>
  {''.join(cards)}
  <div class="footer">自动生成于 {date_str} · 早盘分析 → 午盘分析 → 终盘预测 全程存档可追溯 · <a href="../index.html">返回首页</a></div>
</div>
</body>
</html>"""
    os.makedirs(os.path.join("data", "output"), exist_ok=True)
    out_path = os.path.join("data", "output", f"analysis_{stage}_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[分析存档] {stage_banner}七维分析已保存 → {out_path}")
    return out_path


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python pipeline/analysis_page.py <日期YYYY-MM-DD> <morning|midday>")
        sys.exit(1)
    date_str, stage = sys.argv[1], sys.argv[2]
    pred_path = os.path.join("data", "output", f"predictions_{date_str}.json")
    notes_path = os.path.join("data", "output", f"analysis_notes_{stage}_{date_str}.json")
    if not os.path.exists(pred_path):
        print(f"未找到预测JSON: {pred_path}")
        sys.exit(1)
    with open(pred_path, "r", encoding="utf-8") as f:
        predictions = json.load(f)
    notes = {}
    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            notes = json.load(f)
    intel_text = ""
    intel_path = os.path.join("data", "intel", f"{date_str}.txt")
    if os.path.exists(intel_path):
        with open(intel_path, "r", encoding="utf-8") as f:
            intel_text = f.read().strip()
    fpl_path = os.path.join("data", "intel", f"fpl_{date_str}.txt")
    if os.path.exists(fpl_path):
        with open(fpl_path, "r", encoding="utf-8") as f:
            fpl_text = f.read().strip()
        if fpl_text:
            intel_text = (intel_text + chr(10) + chr(10) + fpl_text).strip() if intel_text else fpl_text
    generate_analysis_page(date_str, stage, predictions, notes, intel_text)


if __name__ == "__main__":
    main()
