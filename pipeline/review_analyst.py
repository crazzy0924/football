# -*- coding: utf-8 -*-
"""
复盘审计 (2026-08-19 重写, 参考 ajunai-football 通用审计规则)

格式: 赛后审计报告 (P0/P1/P2 问题分级), 不再使用 ✅/❌ 流水账:
  A 比赛与结果核验 / B 赛前结论存档(盲测) / C 逐项对照表(判定+等级)
  D 错因归因(P0/P1/P2: 问题/证据/影响/行动) / E 赔率与资金流回顾
  F 教训 / G 盲测声明

用法:
  python pipeline/review_analyst.py <日期YYYY-MM-DD> [赛事备注]
流水线: pipeline.py cmd_review 末尾自动调用 generate_review_analysis()
"""
from __future__ import annotations

import glob
import html as _html
import json
import os
import re as _re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CSS = """
  :root { --bg:#0b0f1a; --card:#121a2c; --line:#1e2a42; --txt:#e9eef8; --dim:#8d99b0;
          --green:#34d399; --amber:#fbbf24; --blue:#5ea8ff; --red:#f87171; --violet:#a78bfa; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:radial-gradient(1000px 400px at 20% -10%, rgba(94,168,255,.12), transparent 60%), var(--bg);
         color:var(--txt); min-height:100vh; padding:28px 16px 40px; line-height:1.6; }
  .container { max-width:900px; margin:0 auto; }
  .hero { text-align:center; padding:30px 10px 20px; }
  .badge { display:inline-block; font-size:.8rem; color:#bfd7ff;
           background:linear-gradient(135deg, rgba(94,168,255,.16), rgba(167,139,250,.14));
           border:1px solid rgba(94,168,255,.35); padding:5px 16px; border-radius:999px; }
  .hero h1 { font-size:1.9rem; font-weight:800; margin-top:12px;
             background:linear-gradient(90deg,#e9eef8,#9ec4ff 60%,#c4b5fd);
             -webkit-background-clip:text; background-clip:text; color:transparent; }
  .hero-sub { color:var(--dim); font-size:.85rem; margin-top:8px; }
  .summary { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:14px 0 24px; }
  .s-box { background:linear-gradient(180deg,var(--card),#101725); border:1px solid var(--line);
           border-radius:12px; padding:12px 6px; text-align:center; }
  .s-box .v { font-size:1.3rem; font-weight:800; }
  .s-box .l { font-size:.72rem; color:var(--dim); }
  .match { background:linear-gradient(180deg,var(--card),#101725); border:1px solid var(--line);
           border-radius:14px; padding:18px; margin:14px 0; }
  .m-head { display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; }
  .m-teams { font-size:1.2rem; font-weight:800; }
  .m-score { font-size:1.3rem; font-weight:800; color:var(--blue); }
  .sec-title { font-size:.82rem; font-weight:800; letter-spacing:1px; color:#9ec4ff; margin:14px 0 6px; }
  .tb-wrap { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-size:.82rem; min-width:520px; }
  th, td { border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top; }
  th { color:#a8c7f0; background:#0e1526; font-size:.75rem; }
  .verdict-hit { color:var(--green); font-weight:700; }
  .verdict-miss { color:var(--red); font-weight:700; }
  .verdict-push, .verdict-na { color:var(--dim); }
  .sev { display:inline-block; border-radius:5px; padding:1px 8px; font-size:.7rem; font-weight:800; }
  .sev-p0 { background:rgba(248,113,113,.18); color:#fca5a5; border:1px solid rgba(248,113,113,.4); }
  .sev-p1 { background:rgba(251,191,36,.14); color:#fcd34d; border:1px solid rgba(251,191,36,.4); }
  .sev-p2 { background:rgba(94,168,255,.14); color:#93c5fd; border:1px solid rgba(94,168,255,.4); }
  .sev-none { background:rgba(52,211,153,.10); color:#6ee7b7; border:1px solid rgba(52,211,153,.35); }
  .arch { background:#0a1120; border:1px dashed #2c3c5c; border-radius:10px; padding:10px 14px;
          font-size:.8rem; color:var(--dim); white-space:pre-wrap; }
  .attr { margin-top:8px; background:#0e1526; border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
  .attr .q { font-size:.85rem; color:var(--txt); }
  .attr .meta { font-size:.75rem; color:var(--dim); margin-top:3px; }
  .lesson { font-size:.85rem; color:#cbd5e8; margin-top:6px; padding-left:18px; }
  .decl { font-size:.75rem; color:var(--dim); margin-top:10px; border-top:1px dashed var(--line); padding-top:8px; }
  .footer { text-align:center; color:var(--dim); font-size:.78rem; margin-top:26px; }
  a { color:#38bdf8; text-decoration:none; }
"""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _cn(name: str) -> str:
    """英文队名转中文 (与预测页同源, 页面队名全中文)"""
    try:
        from pipeline.reporter import TEAM_CN
        return TEAM_CN.get(name, name)
    except Exception:
        return name


def _cn_llm(obj, home: str, away: str):
    """递归清洗 LLM 输出里的英文队名与连续英文词组 (汉化纪律)"""
    if isinstance(obj, dict):
        return {k: _cn_llm(v, home, away) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_cn_llm(v, home, away) for v in obj]
    if isinstance(obj, str):
        try:
            from pipeline.reporter import TEAM_CN
            for en in (home, away):
                if en and en in obj:
                    obj = obj.replace(en, TEAM_CN.get(en, en))
        except Exception:
            pass
        obj = _re.sub(r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*)+", "", obj)
        return _re.sub(r"\s{2,}", " ", obj).strip()
    return obj


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_drift(date_str: str) -> dict:
    """全天赔率变动: (home,away) -> 描述字符串"""
    snaps = sorted(glob.glob(os.path.join("data", "state", "odds_snapshots", f"snapshot_{date_str}_*.json")))
    if len(snaps) < 2:
        return {}
    first, last = snaps[0], snaps[-1]
    a_list = _load_json(first) or []
    b_list = _load_json(last) or []
    b_map = {(m.get("home_team"), m.get("away_team")): m for m in b_list}
    out = {}
    for m in a_list:
        key = (m.get("home_team"), m.get("away_team"))
        bm = b_map.get(key)
        if not bm:
            continue
        oa, ob = m.get("odds") or {}, bm.get("odds") or {}
        lines = []
        if oa.get("home") and ob.get("home"):
            lines.append(
                f"SPF: 主{oa['home']:.2f}→{ob['home']:.2f} 平{oa.get('draw', 0):.2f}→{ob.get('draw', 0):.2f} 客{oa['away']:.2f}→{ob['away']:.2f}"
            )
        if m.get("over_odds") and bm.get("over_odds"):
            lines.append(
                f"大小球: 大{m['over_odds']:.2f}→{bm['over_odds']:.2f} 小{m['under_odds']:.2f}→{bm['under_odds']:.2f}"
            )
        out[key] = "\n".join(lines)
    return out


def _parse_llm(note: str) -> dict | None:
    """解析 LLM 复盘 JSON (取首尾花括号之间的部分)"""
    if not note:
        return None
    text = note.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _query_postmortem(prompt: str) -> str:
    """赛后归因 LLM (独立审计人格)"""
    try:
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("ALL_PROXY", None)
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=DEEPSEEK_API_KEY, disable_thinking_by_default=True)
        resp = client.chat(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content":
                    "你是足球赛后审计员。比赛已结束。严格按用户要求的JSON格式输出, 问题等级只用 P0/P1/P2, 纯中文, 不编造。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.7,
        )
        msg = resp.get("message") or {}
        return (msg.get("content") or "").strip()
    except Exception as e:
        print(f"  [复盘LLM] 失败: {e}")
        return ""


def _match_intel(intel_text: str, home: str, away: str) -> str:
    """从情报账本里抽取本场相关片段 (球队段落 + 裁判/天气中含队名的行)"""
    if not intel_text:
        return "无当日情报账本"
    out = []
    cur_team = None
    for line in intel_text.splitlines():
        s = line.strip()
        if s.startswith("[") and "]" in s:
            cur_team = s[1:s.index("]")]
        if home in s or away in s:
            out.append(s)
        elif cur_team and (home in cur_team or away in cur_team):
            out.append(s)
    return "\n".join(out[:14]) if out else "情报账本中无本场相关条目"


def _build_postmortem_prompt(pred: dict, result: dict, drift_txt: str, competition_note: str,
                             verdict_rows: list, intel_excerpt: str, audit_warning: str) -> str:
    home = pred.get("home_team", "?")
    away = pred.get("away_team", "?")
    m = pred.get("model", {})
    bayes = pred.get("bayesian") or {}
    post = bayes.get("posterior") or {}
    probs = (post.get("home", m.get("home_win", 0)), post.get("draw", m.get("draw", 0)), post.get("away", m.get("away_win", 0)))
    pick_label = ("主胜", "平局", "客胜")[max(range(3), key=lambda i: probs[i])]
    sd = m.get("score_distribution") or {}
    top_scores = sorted(sd.items(), key=lambda kv: -kv[1])[:3]
    top_score_txt = " ".join(f"{s}({p:.0%})" for s, p in top_scores)
    ou_txt = "无信号"
    ou_v = pred.get("ou_value")
    if ou_v:
        ou_txt = f"{ou_v['side']} (edge {ou_v.get('edge', 0):+.0%})"
    ah_txt = "无"
    ah = pred.get("ah_handicap") or {}
    if ah.get("edge") and ah["edge"].get("best_pick"):
        ah_txt = f"倾向{ah['edge']['best_pick']} (让{ah.get('goal_line', 0):+g}球, edge {ah['edge'].get('edge', 0):+.0%})"
    btts_txt = f"模型BTTS {m.get('btts', 0):.0%}"
    verdict_txt = "\n".join(f"- {it}: {de} → 判定{vd} (等级{sev})" for it, de, vd, sev in verdict_rows)
    hg, ag = result.get("home_goals"), result.get("away_goals")
    lines = [
        "你是足球赛后审计员。比赛已结束。请对赛前报告做四维度赛后审计: 胜平负 / 大小球 / 让球 / 波胆。",
        "",
        f"比赛: {home} vs {away} ({pred.get('league_code', '')})",
        f"赛事备注: {competition_note or '无'}",
        f"实际赛果: {hg} - {ag} (总进球{hg + ag if hg is not None else '?'}球, BTTS={'是' if hg and ag else '否'})",
        "",
        "赛前预测存档 (盲测: 只能引用):",
        f"- 胜平负: {pick_label} {max(probs):.1%} (主{probs[0]:.1%}/平{probs[1]:.1%}/客{probs[2]:.1%})",
        f"- 大小球: {ou_txt}",
        f"- 让球: {ah_txt}",
        f"- 波胆(前三): {top_score_txt} · {btts_txt}",
        f"- 冷启动: {'是(已标注)' if pred.get('cold_start') else '否'}",
        "",
        "逐项判定 (已计算, 不要重算):",
        verdict_txt,
    ]
    if drift_txt:
        lines += ["", "全天赔率变动 (复盘用):", drift_txt]
    if audit_warning:
        lines += ["", f"赛前自检当时预警: {audit_warning}"]
    if intel_excerpt:
        lines += ["", f"当日场外情报账本(本场相关):\n{intel_excerpt}"]
    lines += [
        "",
        "审计要求:",
        "- 四个维度每个都要归因: 错在哪, 与全天赔率变动是否有关(资金流是否预示了结果), 与场外情报(伤停/战意/轮换/裁判)是否有关, 赛前自检是否已预警",
        "- 查漏补缺: 赛前有哪些本可获取但没注意到的信息/信号 (结合情报账本和赔率变动逐条找), 最多4条",
        "- 问题分级 P0/P1/P2; 冷启动已标注不算借口, 必须写具体盲区; 不得把同一事实拆成多条凑数",
        "",
        "输出 (只输出一个合法JSON对象, 纯中文):",
        '{',
        '  "结果定性": "常规兑现 / 冷门路径兑现 / 爆冷 / 均势偏差 (一句)",',
        '  "维度复盘": {',
        '    "胜平负": {"归因":"错在哪/为何命中, 与赔率变动及场外情报的关联"},',
        '    "大小球": {"归因":"..."},',
        '    "让球": {"归因":"..."},',
        '    "波胆": {"归因":"..."}',
        '  },',
        '  "查漏补缺": ["赛前没注意到的信息/信号, 每条一句, 最多4条"],',
        '  "教训": ["可执行的规则改进, 最多3条"],',
        '  "赔率回顾": "全天赔率与资金流是否预示了结果, 一句"',
        '}',
    ]
    return "\n".join(lines)


def _check_1x2(pred: dict, actual: str) -> tuple:
    """返回 (判定, 问题等级, 说明)"""
    m = pred.get("model", {})
    bayes = pred.get("bayesian") or {}
    post = bayes.get("posterior") or {}
    probs = [post.get("home", m.get("home_win", 0)), post.get("draw", m.get("draw", 0)), post.get("away", m.get("away_win", 0))]
    labels = ["主胜", "平局", "客胜"]
    pick_i = max(range(3), key=lambda i: probs[i])
    actual_label = {"H": "主胜", "D": "平局", "A": "客胜"}[actual]
    if pick_i == {"H": 0, "D": 1, "A": 2}[actual]:
        return "命中", "无", f"预测{labels[pick_i]} {max(probs):.0%} → 实际{actual_label}"
    if probs[pick_i] >= 0.50:
        sev = "P1"
        why = f"赛前方向概率{max(probs):.0%}未兑现, 属爆冷/高置信误判"
    elif pred.get("cold_start"):
        sev = "P1"
        why = "冷启动场次, 方向判断跟随市场盲定价"
    else:
        sev = "P2"
        why = "均势场方向偏差"
    return "未中", sev, f"预测{labels[pick_i]} {max(probs):.0%} → 实际{actual_label} ({why})"


def _check_ou(pred: dict, goals: int) -> tuple | None:
    ou_v = pred.get("ou_value")
    if not ou_v:
        return None
    over = goals > 2.5
    pick_over = ou_v["side"] == "大2.5"
    txt = f"模型倾向{ou_v['side']} → 实际{'大球' if over else '小球'}({goals}球)"
    if pick_over == over:
        return "命中", "无", txt
    return "未中", "P2", txt


def _check_ah(pred: dict, result: dict) -> tuple | None:
    ah = pred.get("ah_handicap") or {}
    e = ah.get("edge") or {}
    if not e.get("best_pick"):
        return None
    gl = ah.get("goal_line", 0)
    hg, ag = result.get("home_goals") or 0, result.get("away_goals") or 0
    margin = (hg - ag) + gl
    cover = "home" if margin > 0 else ("push" if margin == 0 else "away")
    pick = e["best_pick"]
    if cover == "push":
        return "走盘", "无", f"模型倾向{pick} → 实际走盘(退款)"
    ok = pick == cover
    txt = f"模型倾向{pick} → 实际{'主赢盘' if cover == 'home' else '客赢盘'}"
    return ("命中", "无", txt) if ok else ("未中", "P2", txt)


def _check_score(pred: dict, result: dict) -> tuple | None:
    m = pred.get("model", {})
    sd = m.get("score_distribution") or {}
    if not sd:
        return None
    best = max(sd.items(), key=lambda kv: kv[1])[0]
    actual = f"{result.get('home_goals')}-{result.get('away_goals')}"
    if best == actual:
        return "命中", "无", f"最可能比分 {best} → 实际 {actual}"
    return "未中", "P2", f"最可能比分 {best} ({sd[best]:.0%}) → 实际 {actual}"


def _check_cold_path(pred: dict, result: dict) -> tuple | None:
    """冷门路径是否兑现 (赛前概率最低的方向)"""
    m = pred.get("model", {})
    bayes = pred.get("bayesian") or {}
    post = bayes.get("posterior") or {}
    probs = [post.get("home", m.get("home_win", 0)), post.get("draw", m.get("draw", 0)), post.get("away", m.get("away_win", 0))]
    min_i = min(range(3), key=lambda i: probs[i])
    actual_i = {"H": 0, "D": 1, "A": 2}.get(result.get("result", ""))
    if actual_i is None:
        return None
    if min_i == actual_i and probs[min_i] < 0.40:
        lab = ("主胜", "平局", "客胜")[min_i]
        return "命中", "无", f"赛前最低概率方向 {lab} ({probs[min_i]:.0%}) 兑现 — 冷门路径"
    return None


def generate_review_analysis(date_str: str, matched: list, output_dir: str = "data/output",
                             competition_note: str = "") -> str:
    """生成赛后审计页 (P0/P1/P2 分级), 返回文件路径"""
    predictions = _load_json(os.path.join(output_dir, f"predictions_{date_str}.json")) or []
    drift_map = _load_drift(date_str)
    intel_path = os.path.join("data", "intel", f"{date_str}.txt")
    if os.path.exists(intel_path):
        with open(intel_path, "r", encoding="utf-8") as _f:
            intel_text = _f.read().strip()
    # 终盘自检预警 (审计复盘时回看: 当时自检说了什么)
    audit_map = {}
    notes_path = os.path.join(output_dir, f"analysis_notes_final_{date_str}.json")
    notes_all = _load_json(notes_path) or {}
    for _k, _v in notes_all.items():
        _mm = _re.search(r"自检[:：]\s*(.+)", _v or "")
        if _mm:
            audit_map[_k] = _mm.group(1).strip()

    n_hit = 0
    n_p1 = 0
    n_p2 = 0
    cards = []
    for m in matched:
        home = m.get("home_team", "?")
        away = m.get("away_team", "?")
        home_cn = _cn(home)
        away_cn = _cn(away)
        key = (home, away)
        pred = next((p for p in predictions
                     if (p.get("home_team") == home and p.get("away_team") == away)
                     or (p.get("home_team") == away and p.get("away_team") == home)), None)
        result = {"home_goals": m.get("home_goals"), "away_goals": m.get("away_goals"), "result": m.get("actual")}
        drift_txt = drift_map.get(key, "")
        goals = (m.get("home_goals") or 0) + (m.get("away_goals") or 0)

        # C 逐项对照 (确定性计算: 胜平负/波胆/冷门路径/大小球/让球)
        rows = []
        chk = _check_1x2(pred or m, m.get("actual", ""))
        rows.append(("胜平负方向", chk[2], chk[0], chk[1]))
        sc = _check_score(pred or {}, result)
        if sc:
            rows.append(("最可能比分", sc[2], sc[0], sc[1]))
        cp = _check_cold_path(pred or {}, result)
        if cp:
            rows.append(("冷门路径", cp[2], cp[0], cp[1]))
        ou = _check_ou(pred or {}, goals)
        if ou:
            rows.append(("大小球", ou[2], ou[0], ou[1]))
        ah = _check_ah(pred or {}, result)
        if ah:
            rows.append(("让球盘", ah[2], ah[0], ah[1]))
        for _, _, vd, sev in rows:
            if vd == "命中":
                n_hit += 1
            if sev == "P1":
                n_p1 += 1
            elif sev == "P2":
                n_p2 += 1

        # D 四维归因 (LLM: 结合赔率变动+场外情报+自检预警)
        llm = {}
        if pred:
            try:
                intel_excerpt = _match_intel(intel_text, home, away)
                audit_warning = audit_map.get(f"{home} vs {away}", "") or audit_map.get(f"{away} vs {home}", "")
                prompt2 = _build_postmortem_prompt(pred, result, drift_txt, competition_note,
                                                    rows, intel_excerpt, audit_warning)
                note = _query_postmortem(prompt2)
                llm = _cn_llm(_parse_llm(note) or {}, home, away)
                print(f"  [复盘审计] {home} vs {away}: 维度归因 {len(llm.get('维度复盘') or dict())} 项, 查漏 {len(llm.get('查漏补缺') or [])} 条")
            except Exception as e:
                print(f"  [复盘审计] {home} vs {away} 失败: {e}")

        rows_html = "".join(
            '<tr><td>' + _esc(item) + '</td><td>' + _esc(detail) + '</td>'
            + '<td class="verdict-' + ("hit" if vd == "命中" else "miss" if vd == "未中" else "push" if vd == "走盘" else "na") + '">' + _esc(vd) + '</td>'
            + '<td><span class="sev sev-' + ("p0" if sev == "P0" else "p1" if sev == "P1" else "p2" if sev == "P2" else "none") + '">' + _esc(sev) + '</span></td></tr>'
            for item, detail, vd, sev in rows
        )
        # D 维度复盘渲染: 四维度 + LLM 归因
        dim_map = {}
        for item, detail, vd, sev in rows:
            dim_map.setdefault(item, (vd, sev))
        dim_rev = llm.get("维度复盘") or {}
        dim_html = ""
        for label, keyname in (("胜平负", "胜平负方向"), ("波胆", "最可能比分"), ("大小球", "大小球"), ("让球", "让球盘")):
            vd, sev = dim_map.get(keyname, (None, None))
            if vd is None:
                continue
            rv = dim_rev.get(label) or {}
            reason = rv.get("归因", "") if isinstance(rv, dict) else str(rv)
            vcls = "hit" if vd == "命中" else "miss" if vd == "未中" else "push" if vd == "走盘" else "na"
            dim_html += ('<div class="attr"><div class="q"><span class="verdict-' + vcls + '">' + _esc(vd) + '</span> <b>' + _esc(label) + '</b></div>'
                         + '<div class="meta">归因: ' + _esc(reason or "—") + '</div></div>')
        gaps = "".join('<li class="lesson">' + _esc(x) + '</li>' for x in (llm.get("查漏补缺") or []))
        lessons = "".join('<li class="lesson">' + _esc(x) + '</li>' for x in (llm.get("教训") or []))
        comp_txt = " · 赛事备注: " + competition_note if competition_note else ""
        cards.append("""
<article class="match">
  <header class="m-head">
    <div class="m-teams">""" + _esc(home_cn) + """ <span style="color:#8d99b0;">VS</span> """ + _esc(away_cn) + """</div>
    <div class="m-score">""" + _esc(str(m.get("home_goals", "?"))) + " - " + _esc(str(m.get("away_goals", "?"))) + """</div>
  </header>
  <div class="sec-title">A · 比赛与结果核验</div>
  <div class="arch">赛果 """ + _esc(str(m.get("home_goals", "?"))) + " - " + _esc(str(m.get("away_goals", "?"))) + " · 联赛 " + _esc(pred.get("league_code", "") if pred else "?") + _esc(comp_txt) + " · 结果定性: " + _esc((llm.get("结果定性") or "待归因")) + """</div>
  <div class="sec-title">C · 四维逐项对照 (胜平负/波胆/大小球/让球)</div>
  <div class="tb-wrap"><table>
    <tr><th style="width:100px;">预测项</th><th>赛前预测 → 实际</th><th style="width:64px;">判定</th><th style="width:60px;">等级</th></tr>
""" + rows_html + """
  </table></div>
  <div class="sec-title">D · 四维归因 (关联赔率变动/场外情报/自检预警)</div>
""" + dim_html + """
  <div class="sec-title">E · 查漏补缺 (赛前没注意到的信息/信号)</div>
""" + ('<ul>' + gaps + '</ul>' if gaps else '<div class="arch">—</div>') + """
  <div class="sec-title">F · 赔率与资金流回顾</div>
  <div class="arch">""" + _esc((llm.get("赔率回顾") or "") or (drift_txt or "当日无赔率快照")) + """</div>
  <div class="sec-title">G · 教训</div>
""" + ('<ul>' + lessons + '</ul>' if lessons else '<div class="arch">—</div>') + """
  <div class="decl">H · 盲测声明: 赛前报告已于 """ + _esc(date_str) + """ 存档, 本复盘不事后修改赛前结论; 所有判定基于存档原文与最终赛果。</div>
</article>""")
    total = len(matched)
    summary = f"""
  <div class="summary">
    <div class="s-box"><div class="v">{total}</div><div class="l">审计场次</div></div>
    <div class="s-box"><div class="v" style="color:#6ee7b7;">{n_hit}</div><div class="l">命中项</div></div>
    <div class="s-box"><div class="v" style="color:#fcd34d;">{n_p1}</div><div class="l">P1 重要问题</div></div>
    <div class="s-box"><div class="v" style="color:#93c5fd;">{n_p2}</div><div class="l">P2 一般问题</div></div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>赛后审计 — {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="badge">📋 赛后审计 · P0/P1/P2 问题分级 (参考通用审计规则)</div>
    <h1>{date_str}</h1>
    <div class="hero-sub">赛前预测 vs 赛果逐项对账 · 错因归因 · 规则改进 · 数据台账见 <a href="review_{date_str}.html">review_{date_str}.html</a></div>
  </div>
  {summary}
  {''.join(cards)}
  <div class="footer">自动生成 · 盲测纪律: 赛前结论事后不改写 · <a href="../index.html">返回首页</a></div>
</div>
</body>
</html>"""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"review_analysis_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[复盘审计] 已保存 → {out_path}")
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python pipeline/review_analyst.py <日期YYYY-MM-DD> [赛事备注]")
        sys.exit(1)
    date_str = sys.argv[1]
    competition_note = sys.argv[2] if len(sys.argv) > 2 else ""
    pred_path = os.path.join("data", "output", f"predictions_{date_str}.json")
    results_path = os.path.join("data", "output", f"results_{date_str}.json")
    if not os.path.exists(pred_path) or not os.path.exists(results_path):
        print("缺少预测或赛果文件, 无法复盘")
        sys.exit(1)
    from pipeline.result_fetcher import match_predictions_to_results
    preds = json.load(open(pred_path, encoding="utf-8"))
    res = json.load(open(results_path, encoding="utf-8"))
    matched = match_predictions_to_results(preds, res)
    generate_review_analysis(date_str, matched, competition_note=competition_note)


if __name__ == "__main__":
    main()
