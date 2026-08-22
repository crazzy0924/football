"""
HTML Report Generator v3.0

Renders predictions JSON → single professional HTML report via Jinja2.
Replaces 30+ manual HTML files with one template.

Usage:
    from pipeline.reporter import generate_report
    generate_report(predictions, output_path)
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any


# 联赛代码 → 显示名
LEAGUE_NAMES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
}

# League code → 中文名
LEAGUE_NAMES_CN = {
    "PL": "英超",
    "PD": "西甲",
    "BL1": "德甲",
    "SA": "意甲",
    "FL1": "法甲",
    # 非五大联赛 (体彩开盘, 分析为主)
    "ELC": "英冠", "BL2": "德乙", "FL2": "法乙",
    "DED": "荷甲", "DED2": "荷乙", "PPL": "葡超",
    "FIN": "芬超", "SWE": "瑞超", "NOR": "挪超", "NO1": "挪超",
    "J1": "日职", "KLEAGUE": "韩职", "BSA": "巴甲", "MLS": "美职", "SPL": "沙职",
    "UCL": "欧冠", "UEL": "欧联", "CLB": "解放者杯",
}

# English → 中文 team name mapping
TEAM_CN = {
    # 日职/日乙
    "Tokyo Verdy": "东京绿茵",
    "Kawasaki Frontale": "川崎前锋",
    "V-Varen Nagasaki": "长崎成功丸",
    "Kyoto Sanga": "京都不死鸟",
    "Montedio Yamagata": "山形山神",
    "Tochigi SC": "栃木SC",
    "Cottbus": "科特布斯",
    "Hannover": "汉诺威96",
    # 荷甲
    "Sparta Rotterdam": "鹿特丹斯巴达",
    "Feyenoord": "费耶诺德",
    "Zwolle": "兹沃勒",
    "Ajax": "阿贾克斯",
    "Groningen": "格罗宁根",
    "Utrecht": "乌得勒支",
    "Heerenveen": "海伦芬",
    "Twente": "特温特",
    # 德乙
    "St Pauli": "圣保利",
    "Greuther Furth": "菲尔特",
    "Nurnberg": "纽伦堡",
    "Dresden": "德累斯顿",
    # 瑞典超
    "Hammarby": "哈马比",
    "Hacken": "赫根",
    "Halmstads": "哈尔姆斯塔德",
    "GAIS": "哥德堡盖斯",
    "IFK Goteborg": "IFK哥德堡",
    "Kalmar": "卡尔马",
    "Malmo": "马尔默",
    "Degerfors": "代格福什",
    # 芬超
    "KuPS": "库普斯",
    "TPS": "TPS图尔库",
    "Inter Turku": "国际图尔库",
    "Lahti": "拉赫蒂",
    "Ilves": "伊尔韦斯",
    "Mariehamn": "玛丽港",
    "AC Oulu": "AC奥卢",
    "HJK": "HJK赫尔辛基",
    "HJK Helsinki": "HJK赫尔辛基",
    # 挪超
    "Lillestrom": "利勒斯特伦",
    "Rosenborg": "罗森博格",
    "HamKam": "汉坎",
    "Aalesund": "奥勒松",
    "Kristiansund": "克里斯蒂安松",
    "Molde": "莫尔德",
    # 葡超
    "Porto": "波尔图",
    "Alverca": "阿尔维卡",
    "Benfica": "本菲卡",
    "Viseu": "维塞乌",
    "Gil Vicente": "吉维森特",
    "Rio Ave": "里奥阿维",
    "Moreirense": "莫雷伦斯",
    "Sp Braga": "布拉加",
    "Braga": "布拉加",
    # 巴甲
    "Santos": "桑托斯",
    "Athletico-PR": "巴拉纳竞技",
    "Flamengo": "弗拉门戈",
    "Guimaraes": "吉马良斯",
    "Vitoria Guimaraes": "吉马良斯",
    "Vitoria": "维多利亚",
    "Cruzeiro": "克鲁塞罗",
    "Mirassol": "米拉索尔",
    "Bahia": "巴伊亚",
    "Vasco": "瓦斯科达伽马",
    "Palmeiras": "帕尔梅拉斯",
    "Paris SG": "巴黎圣日尔曼",
    "Paris Saint-Germain": "巴黎圣日尔曼",
    "Aston Villa": "阿斯顿维拉",
    "Coquimbo Unido": "科金博联",
    "Cerro Porteno": "波特诺山丘",
    "Platense": "普拉滕斯",
    "Abha": "艾卜哈",
    "Al Hazm": "哈森姆",
    "Universitatea Craiova": "克拉约瓦大学",
    "Pafos": "帕福斯",
    "Salzburg": "萨尔茨堡",
    "Vikingur Reykjavik": "雷克雅未克维京人",
    "Thun": "图恩",
    "Al Shabab": "利雅得青年",
    "Al Qadsiah": "胡巴尔卡德西亚",
    "Rangers": "格拉斯哥流浪者",
    "Jagiellonia": "比亚韦斯托克",
    "Anderlecht": "安德莱赫特",
    "PAOK": "塞萨洛尼基",
    "Hearts": "哈茨",
    "LDU Quito": "基多体育大学",
    "Rosario Central": "罗萨里奥中央",
    "Internacional": "巴西国际",
    "Bragantino": "布拉甘蒂诺",
    "Corinthians": "科林蒂安",
    # 美职联/LCUP
    "Austin FC": "奥斯汀FC",
    "Puebla": "普埃布拉",
    "San Diego FC": "圣地亚哥FC",
    "Tijuana": "蒂华纳",
    "Club America": "美洲",
    "Portland Timbers": "波特兰伐木者",
    "IK Sirius": "天狼星",
    "IF Brommapojkarna": "布鲁马波卡纳",
    "Vasteras SK": "韦斯特罗斯",
    "Västerås SK": "韦斯特罗斯",
    "Djurgardens IF": "佐加顿斯",
    "Djurgårdens IF": "佐加顿斯",
    "Santa Clara": "圣克拉拉",
    "Nacional": "葡萄牙国民",
    # 俄超/其他
    "CSKA Moscow": "莫斯科中央陆军",
    "Spartak Moscow": "莫斯科斯巴达",
    "Zenit": "泽尼特",
    "Krasnodar": "克拉斯诺达尔",
    "Lokomotiv Moscow": "莫斯科火车头",
    "Dinamo Moscow": "莫斯科迪纳摩",
    # 8月14日晚场16场全量 (汉化补漏)
    "IF Elfsborg": "埃尔夫斯堡",
    "Vaasan PS": "瓦萨",
    "Holstein Kiel": "基尔",
    "Braunschweig": "不伦瑞克",
    "Bochum": "波鸿",
    "Neom": "内姆",
    "Al Majmaah": "迈季迈阿",
    "Viking FK": "维京",
    "Al Ettifaq": "达曼协作",
    "Al Riyadh": "利雅得",
    "Telstar": "特尔斯达",
    "Waalwijk": "瓦尔韦克",
    "Heracles": "赫拉克勒斯",
    "Den Bosch": "登博思",
    "Dordrecht": "多德勒支",
    "Blackburn": "布莱克本",
    "Al Faisaly": "费萨利",
    "Al Hilal": "利雅得新月",
    "Annecy": "阿纳西",
    "Rodez": "罗代兹",
    "Reims": "兰斯",
    "Dunkerque": "敦刻尔克",
    "St Etienne": "圣埃蒂安",
    "Clermont": "克莱蒙",
    "Wolves": "狼队",
    "Sp Lisbon": "里斯本竞技",
    "Kashiwa Reysol": "柏太阳神",
    # 赔率outcome词 (赔率行汉化)
    "Home": "主",
    "Draw": "平",
    "Away": "客",
    "None": "无",
}

# 自动同步: 从 team_names 的 CN→EN 表反向生成 EN→CN (手工表优先, 缺则回退英文)
try:
    from pipeline.team_names import CN_TO_EN_TEAM
    for _cn_name, _en_name in CN_TO_EN_TEAM.items():
        TEAM_CN.setdefault(_en_name, _cn_name)
except Exception:
    pass

def _cn(home_team: str, away_team: str) -> tuple[str, str]:
    """Return Chinese team names for a match pair."""
    return TEAM_CN.get(home_team, home_team), TEAM_CN.get(away_team, away_team)

SIGNAL_CLASSES = {
    "high": "bet",
    "medium": "watch",
    "low": "watch",
    "none": "skip",
}

SIGNAL_TEXTS = {
    "high": "投注",
    "medium": "关注",
    "low": "参考",
    "none": "跳过",
}


def generate_report(
    predictions: list[dict],
    output_dir: str = "data/output",
    output_name: str | None = None,
    backtest_brier: float | None = None,
    analyst_notes: dict[str, str] | None = None,
) -> str:
    """Generate HTML report from predictions list.

    Args:
        predictions: list of prediction dicts from cmd_predict
        output_dir: output directory
        output_name: output filename (defaults to predictions_YYYY-MM-DD.html)
        backtest_brier: optional backtest Brier score for footer
        analyst_notes: optional dict of "Home vs Away" → note text (from LLM)

    Returns:
        Path to generated HTML file
    """
    today = date.today().isoformat()
    out_name = output_name or f"predictions_{today}.html"
    out_path = os.path.join(output_dir, out_name)

    # 如可用则加载回测Brier
    if backtest_brier is None:
        backtest_brier = _load_backtest_brier(output_dir)

    # 构建模板上下文
    match_cards = []
    for p in predictions:
        card = _build_match_card(p, analyst_notes)
        match_cards.append(card)

    # Summary stats
    total = len(match_cards)
    recommended = sum(1 for m in match_cards if m["recommendation"] == "recommended")
    reference_only = sum(1 for m in match_cards if m["recommendation"] == "reference")
    cold = sum(1 for m in match_cards if m["cold_start_flag"])

    # 胜平负方向分布
    h_picks = sum(1 for m in match_cards if m["pick"] == "主胜")
    d_picks = sum(1 for m in match_cards if m["pick"] == "平局")
    a_picks = sum(1 for m in match_cards if m["pick"] == "客胜")
    direction_dist = f"{h_picks}/{d_picks}/{a_picks}"

    # 今日看好速览 (下注卡片)
    picks = [m for m in match_cards if m["bet_class"] == "bet"]

    # 同日早盘/午盘七维分析存档链接 (终盘页引用, 数据可追溯)
    analysis_links = _build_analysis_links(today, output_dir)

    # 左侧联赛导航分组 (只列出当天有比赛的联赛)
    league_groups = []
    for _g in ("英超", "西甲", "德甲", "意甲", "法甲", "非五大"):
        if any(m["league_group"] == _g for m in match_cards):
            league_groups.append(_g)

    context = {
        "date": today,
        "backtest_brier": f"{backtest_brier:.4f}" if backtest_brier else None,
        "total_matches": total,
        "recommended": recommended,
        "reference": reference_only,
        "cold_start": cold,
        "direction_dist": direction_dist,
        "matches": match_cards,
        "picks": picks,
        "analysis_links": analysis_links,
        "league_groups": league_groups,
    }

    # Render template
    html = _render_template(context)
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML报告已保存 → {out_path}")
    return out_path


# 赔率快照缓存 (同进程内只加载一次)
_odds_movement_cache: dict = {}


def _load_odds_movement(date_str: str) -> dict:
    """加载当日赔率快照, 计算每场主胜赔率变动 (早盘→最新快照)"""
    import glob as _glob
    if _odds_movement_cache.get("date") == date_str:
        return _odds_movement_cache.get("data", {})
    import os as _os
    import json as _json
    snaps = sorted(_glob.glob(os.path.join("data", "state", "odds_snapshots", f"snapshot_{date_str}_*.json")))
    data: dict = {}
    if len(snaps) >= 2:
        first = snaps[0]
        last = snaps[-1]
        try:
            with open(first, "r", encoding="utf-8") as f:
                a_list = _json.load(f)
            with open(last, "r", encoding="utf-8") as f:
                b_list = _json.load(f)
        except Exception:
            a_list, b_list = [], []
        b_map = {(m.get("home_team"), m.get("away_team")): m for m in b_list}
        for m in a_list:
            key = (m.get("home_team"), m.get("away_team"))
            bm = b_map.get(key)
            if not bm:
                continue
            oa = (m.get("odds") or {}).get("home")
            ob = (bm.get("odds") or {}).get("home")
            if oa and ob:
                data[key] = {"from": oa, "to": ob, "delta": round(ob - oa, 3)}
    _odds_movement_cache["date"] = date_str
    _odds_movement_cache["data"] = data
    return data


# 北京时间 → 当地时间的粗略时差 (供比赛核验参考, 标注"约")
_TZ_OFFSET = {"PL": -7, "ELC": -7, "PD": -6, "BL1": -6, "SA": -6, "FL1": -6,
              "DED": -6, "PPL": -7, "CLB": -12, "BSA": -11, "MLS": -12, "SPL": -7}


def _cn_note(note: str, home_en: str, away_en: str) -> str:
    """分析师笔记汉化: 英文队名换中文, 连续英文词组移除 (汉化纪律)"""
    if not note:
        return note
    for en in (home_en, away_en):
        if en and en in note:
            cn = TEAM_CN.get(en)
            if cn:
                note = note.replace(en, cn)
            else:
                note = note.replace(en, "")
    # 兜底: 剩余连续英文词组 (如 "vs LASK") 移除
    note = re.sub(r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*)+", "", note)
    note = re.sub(r"\s{2,}", " ", note).strip()
    return note


def _league_group(league_code: str) -> str:
    """联赛分组键: 五大联赛各自一组, 其余归"非五大" (左侧导航用)"""
    if league_code in ("PL", "PD", "BL1", "SA", "FL1"):
        return {"PL": "英超", "PD": "西甲", "BL1": "德甲", "SA": "意甲", "FL1": "法甲"}[league_code]
    return "非五大"


def _local_time(p: dict, league_code: str) -> str:
    """开球当地时间估算 (北京时间+时差, 约值)"""
    kt = (p.get("kickoff_time") or "").strip()
    if not kt or len(kt) < 5:
        return "—"
    off = _TZ_OFFSET.get(league_code)
    if off is None:
        return "—"
    try:
        hh = (int(kt[:2]) + off) % 24
        return f"约{hh:02d}:{kt[3:5]}"
    except Exception:
        return "—"


def _build_match_card(
    p: dict,
    analyst_notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build template context for a single match card."""
    model = p.get("model", {})
    value = p.get("value") or {}
    bayes = p.get("bayesian") or {}
    odds_data = p.get("odds") or {}

    home_team_en = p.get("home_team", "?")
    away_team_en = p.get("away_team", "?")
    home_team, away_team = _cn(home_team_en, away_team_en)
    league_code = p.get("league_code", "")
    league_name = LEAGUE_NAMES_CN.get(league_code, league_code)
    # 非五大联赛场次: 打标提示 (模型覆盖弱, 市场定价为主)
    try:
        from config import FOCUS_LEAGUES
        if league_code not in FOCUS_LEAGUES:
            league_name = league_name + " · 非五大"
    except Exception:
        # 直接跑脚本时 config 不在路径, 按已知五大联赛兜底
        if league_code not in ("PL", "PD", "BL1", "SA", "FL1"):
            league_name = league_name + " · 非五大"
    cold_start = p.get("cold_start", False)
    cross_league = p.get("cross_league", False)
    # 下注门禁统一: 冷启动 或 跨级先验 都不下注
    no_bet = cold_start or cross_league

    # 概率 — 优先贝叶斯后验, 否则用模型
    if bayes and "posterior" in bayes:
        post = bayes["posterior"]
        p_home = post.get("home", model.get("home_win", 0.33))
        p_draw = post.get("draw", model.get("draw", 0.34))
        p_away = post.get("away", model.get("away_win", 0.33))
    else:
        p_home = model.get("home_win", 0.33)
        p_draw = model.get("draw", 0.34)
        p_away = model.get("away_win", 0.33)

    # 从价值检测取方向
    pick_dir = value.get("best_direction", "none")
    if pick_dir == "home":
        pick = "主胜"
    elif pick_dir == "draw":
        pick = "平局"
    elif pick_dir == "away":
        pick = "客胜"
    else:
        # 兜底: 最高概率方向
        best_p = max(p_home, p_draw, p_away)
        if best_p == p_home:
            pick = "主胜"
        elif best_p == p_draw:
            pick = "平局"
        else:
            pick = "客胜"

    # 置信度 / 信号
    confidence = value.get("confidence", "none")

    # 冷启动/跨级先验场次: 模型edge是噪音 → 覆盖信号
    if (cold_start or cross_league) and confidence != "none":
        signal_class = "cold"
        signal_text = "跨级先验" if cross_league and not cold_start else "冷启动"
        confidence = "low"  # downgrade edge for recommendation logic
    else:
        signal_class = SIGNAL_CLASSES.get(confidence, "skip")
        signal_text = SIGNAL_TEXTS.get(confidence, "SKIP")

    # 推荐等级
    if confidence == "high" and not no_bet:
        recommendation = "recommended"
    elif confidence in ("medium", "high") or ((cold_start or cross_league) and confidence != "none"):
        recommendation = "reference"
    else:
        recommendation = "skip"

    # Kelly
    kelly_val = value.get("kelly", 0) or 0
    kelly_text = f"{kelly_val:.2%}" if kelly_val > 0 else None
    kelly_class = "pos" if kelly_val > 0 else "neg"

    # Edge
    edges = {
        "home": value.get("home_edge", 0) or 0,
        "draw": value.get("draw_edge", 0) or 0,
        "away": value.get("away_edge", 0) or 0,
    }
    best_edge_dir = max(edges, key=edges.get)
    best_edge_val = edges[best_edge_dir]
    edge_pct = f"{best_edge_val:.1%}" if best_edge_val > 0 else None

    # 看好方向 (下注栏, CLAUDE.md 纪律): edge≥5% + Kelly≥1% + 非冷启动 + 非无信号
    no_signal = p.get("no_signal", False)
    if no_signal:
        bet_pick = "无信号"
        bet_class = "skip"
    elif cold_start:
        bet_pick = "冷启动不碰"
        bet_class = "cold"
    elif cross_league:
        bet_pick = "跨级先验不碰"
        bet_class = "cold"
    elif best_edge_val >= 0.05 and kelly_val >= 0.01:
        dir_cn = {"home": "主胜", "draw": "平局", "away": "客胜"}.get(best_edge_dir, "观望")
        dir_odds = odds_data.get(best_edge_dir) if odds_data else None
        stake = None
        try:
            from config import BANKROLL
            stake = BANKROLL * kelly_val / 4.0  # 1/4 凯利
        except Exception:
            pass
        stake_txt = f" 建议¥{stake:.0f}" if stake and stake >= 1 else ""
        if dir_odds:
            bet_pick = f"{dir_cn} @{dir_odds:.2f} (凯利{kelly_val:.0%}){stake_txt}"
        else:
            bet_pick = f"{dir_cn} (凯利{kelly_val:.0%}){stake_txt}"
        bet_class = "bet"
    else:
        bet_pick = "观望"
        bet_class = "skip"

    # 赔率变动 (早盘→最新快照, 资金流向参考)
    try:
        from datetime import date as _date
        move_map = _load_odds_movement(_date.today().isoformat())
        move = move_map.get((home_team_en, away_team_en))
        odds_move = None
        if move:
            if move["delta"] < -0.05:
                odds_move = f"主胜赔率↓ {move['from']:.2f}→{move['to']:.2f} (资金流主)"
            elif move["delta"] > 0.05:
                odds_move = f"主胜赔率↑ {move['from']:.2f}→{move['to']:.2f} (资金流客)"
            else:
                odds_move = f"主胜赔率稳定 {move['to']:.2f}"
    except Exception:
        odds_move = None

    # 让球盘 (AH) 参考与备选方向 (维度台账 AH 已过门: Brier 0.1535 vs 0.233)
    ah = p.get("ah_handicap")
    ah_text = None
    ah_pick = None
    if ah:
        line = ah.get("goal_line")
        hc = ah.get("home_cover", 0)
        pu = ah.get("push", 0)
        ac = ah.get("away_cover", 0)
        edge = ah.get("edge") or {}
        bp = edge.get("best_pick", "skip")
        ev = edge.get("edge", 0)
        if line is not None:
            ah_text = f"让球(主{line:+.1f}): 主{hc:.0%}/走{pu:.0%}/客{ac:.0%}"
        # 冷启动纪律: 冷启动场次让球盘也不出"看好", 只展示盘口覆盖
        if bp in ("home", "away") and ev >= 0.05 and not no_bet:
            dir_cn = "主队" if bp == "home" else "客队"
            ah_pick = f"让球看好{dir_cn} (+{ev:.1%})"
            if bet_class != "bet":
                bet_pick = ah_pick
                bet_class = "bet"

    # Market odds
    market_odds_str = None
    if odds_data:
        h = odds_data.get("home", 0)
        d = odds_data.get("draw", 0)
        a = odds_data.get("away", 0)
        if h and d and a:
            market_odds_str = f"{h:.2f}/{d:.2f}/{a:.2f}"

    # Expected goals
    lam_h = model.get("lambda_home", 0)
    lam_a = model.get("lambda_away", 0)
    eg_text = f"{lam_h:.2f} - {lam_a:.2f}" if lam_h > 0 else None

    # Top score (联合约束优先: 与让球盘/大小球倾向自洽)
    top_scores = model.get("top_5_scores", [])
    jt = p.get("joint_top_scores") or []
    top_score_str = jt[0]["score"] if jt else (top_scores[0][0] if top_scores else None)
    # 矛盾修正标记 (原始单格与联合约束不一致时显示)
    score_fix_note = None
    if jt and top_scores and jt[0]["score"] != top_scores[0][0]:
        score_fix_note = f"原始单格最高 {top_scores[0][0]}, 与让球/大小球矛盾, 已修正"

    # ELO
    elo_diff = p.get("elo_diff", 0)

    # 波胆/大小球价值 (Phase 10)
    cs_values = p.get("cs_value") or []
    cs_text = None
    if cs_values:
        cs_text = " · ".join(
            f"{v['score']}(模型{v['model']:.1%}vs市场{v['market']:.1%})" for v in cs_values
        )
    ou_v = p.get("ou_value")
    ou_text = None
    if ou_v:
        ou_text = f"{ou_v['side']} 模型{ou_v['model']:.0%} vs 市场{ou_v['market']:.0%} ({ou_v['edge']:+.0%})"

    # 积分榜快照 (Phase 7)
    std = p.get("standings") or {}
    std_text = None
    sh = std.get("home")
    sa = std.get("away")
    if sh or sa:
        parts = []
        pts_h = sh.get('points') if sh else None
        pts_a = sa.get('points') if sa else None
        if sh:
            p_show = f"({pts_h}分)" if pts_h else ""
            parts.append(f"主队#{sh.get('pos', '?')}{p_show}")
        if sa:
            p_show = f"({pts_a}分)" if pts_a else ""
            parts.append(f"客队#{sa.get('pos', '?')}{p_show}")
        # 新赛季 (两队积分都为0): 标注新赛季, 不显示无意义的0分
        if (pts_h is None or pts_h == 0) and (pts_a is None or pts_a == 0) and (sh or sa):
            parts.append("新赛季首轮")
        std_text = " · ".join(parts) if parts else None
    std_form = None
    if sh and sh.get("form"):
        std_form = f"近况 主[{sh['form']}] 客[{sa.get('form', '')}]" if sa else None
    form_h = (sh or {}).get("form", "")
    form_a = (sa or {}).get("form", "")

    # 比分概率迷你图 (前5比分)
    score_bars = []
    for s, pr in top_scores[:5]:
        score_bars.append({"score": s, "pct": round(pr * 100, 1)})

    # ELO 力量对比
    elo_h = p.get("elo_home") or 0
    elo_a = p.get("elo_away") or 0
    elo_total = elo_h + elo_a
    elo_h_share = round(elo_h / elo_total * 100) if elo_total > 0 else 50

    # 分析师注释 — 按英文名查(键为英文)
    match_key = f"{home_team_en} vs {away_team_en}"
    analyst_note = (analyst_notes or {}).get(match_key)
    # 汉化纪律: 笔记中的英文队名/连续英文词组替换为中文或移除 (否则推送被拦)
    if analyst_note:
        analyst_note = _cn_note(analyst_note, home_team_en, away_team_en)

    # 结构化八维报告 (LLM JSON输出, 参考开源研究框架的 A-I 结构)
    struct = None
    if analyst_note:
        try:
            from pipeline.analyst import parse_structured_note
            struct = parse_structured_note(analyst_note)
        except Exception:
            struct = None
    dims_rows = []
    paths_rows = []
    triggers_list = []
    summary_txt = None
    dir_score = None
    reverse_txt = None
    conf_txt = None
    second_score = None
    tactics = {}
    extended = {}
    if struct:
        summary_txt = struct.get("摘要")
        dir_score = struct.get("方向分")
        reverse_txt = struct.get("反向验证")
        conf_txt = struct.get("置信度")
        second_score = struct.get("次选比分")
        tactics = struct.get("战术") or {}
        extended = struct.get("扩展") or {}
        for d in struct.get("八维") or []:
            dims_rows.append({
                "label": d.get("维度", ""),
                "evidence": d.get("证据", ""),
                "score": d.get("优势分", 0),
                "weight": d.get("权重", 0),
                "conf": d.get("置信度", ""),
                "judge": d.get("研判", ""),
            })
        path_label = {"常规": "常规路径", "平局": "平局路径", "冷门": "冷门路径"}
        # 路径概率取自贝叶斯后验 (合计100%, 硬校准)
        if bayes and "posterior" in bayes:
            post = bayes["posterior"]
            path_prob = {"常规": max(post.values()), "平局": post.get("draw", 0), "冷门": min(post.values())}
        else:
            path_prob = {"常规": p_home, "平局": p_draw, "冷门": min(p_home, p_draw, p_away)}
        for key in ("常规", "平局", "冷门"):
            item = (struct.get("路径") or {}).get(key) or {}
            paths_rows.append({
                "label": path_label[key],
                "prob": f"{path_prob.get(key, 0):.0%}",
                "trigger": item.get("触发", ""),
                "scores": " / ".join(item.get("比分") or []),
            })
        triggers_list = struct.get("触发器") or []

    # 自检结论 (审计行在JSON之外, 单独提取显示)
    audit_txt = None
    if analyst_note:
        m2 = re.search(r"自检[:：]\s*(.+)", analyst_note)
        if m2:
            audit_txt = m2.group(1).strip()

    return {
        "home_team": home_team,
        "away_team": away_team,
        "league": league_name,
        "league_group": _league_group(league_code),
        "p_home": f"{p_home:.1%}",
        "p_draw": f"{p_draw:.1%}",
        "p_away": f"{p_away:.1%}",
        "p_home_pct": round(p_home * 100, 1),
        "p_draw_pct": round(p_draw * 100, 1),
        "p_away_pct": round(p_away * 100, 1),
        "over25": f"{model.get('over_25', 0):.1%}",
        "btts": f"{model.get('btts', 0):.1%}",
        "eg": eg_text or "N/A",
        "top_score": top_score_str or "N/A",
        "score_fix_note": score_fix_note,
        "elo_diff": f"{elo_diff:+.0f}" if elo_diff else "0",
        "market_odds": market_odds_str,
        "pick": pick,
        "signal_class": signal_class,
        "signal_text": signal_text,
        "recommendation": recommendation,
        "kelly_fraction": kelly_text,
        "kelly_class": kelly_class,
        "bet_pick": bet_pick,
        "bet_class": bet_class,
        "ah_text": ah_text,
        "ah_pick": ah_pick,
        "odds_move": odds_move,
        "cs_text": cs_text,
        "ou_text": ou_text,
        "std_text": std_text,
        "std_form": std_form,
        "form_h": form_h,
        "form_a": form_a,
        "score_bars": score_bars,
        "elo_h": round(elo_h),
        "elo_a": round(elo_a),
        "elo_h_share": elo_h_share,
        "edge_direction": best_edge_dir.title() if best_edge_val > 0 else None,
        "edge_pct": edge_pct,
        "cold_start_flag": cold_start,
        "cross_league": cross_league,
        "analyst_note": analyst_note,
        # 结构化八维报告字段
        "summary_txt": summary_txt,
        "dir_score": dir_score,
        "reverse_txt": reverse_txt,
        "dims_rows": dims_rows,
        "paths_rows": paths_rows,
        "triggers_list": triggers_list,
        "kickoff": (p.get("kickoff_time") or ""),
        "venue": (p.get("venue") or "") or "—",
        "anchor_from_ah": p.get("anchor_from_ah", False),
        "flag_texts": " · ".join((p.get("flags") or {}).values()),
        "audit_txt": audit_txt,
        "conf_txt": conf_txt,
        "second_score": second_score,
        "tactics_have_ball": tactics.get("有球") or "",
        "tactics_no_ball": tactics.get("无球") or "",
        "tactics_key_var": tactics.get("最大变量") or "",
        "ext_goals": extended.get("总进球") or "",
        "ext_margin": extended.get("净胜球") or "",
        "ext_first_half": extended.get("上半场") or "",
        "research_time": date.today().isoformat() + " · 终盘",
        "local_time": _local_time(p, league_code),
        "missing_dims": "、".join(
            d.get("label", "") for d in dims_rows
            if ("无数据" in str(d.get("evidence", ""))) or ("未公布" in str(d.get("evidence", "")))
        ),
    }


def _build_analysis_links(date_str: str, output_dir: str) -> str:
    """构建终盘页引用的同日早盘/午盘七维分析存档链接"""
    links = []
    for st, label in (("morning", "早盘七维分析存档"), ("midday", "午盘七维分析存档")):
        p = os.path.join(output_dir, f"analysis_{st}_{date_str}.html")
        if os.path.exists(p):
            links.append(f'<a href="analysis_{st}_{date_str}.html">📋 {label}</a>')
    return " · ".join(links)


def _render_template(context: dict) -> str:
    """Render the Jinja2 template with given context."""
    template = _get_template()
    return template.render(**context)


def _get_template():
    """Lazy-load Jinja2 template."""
    try:
        from jinja2 import Template as Jinja2Template
    except ImportError:
        # 兜底: 简单字符串插值
        return _SimpleTemplate(_read_template_content())

    return Jinja2Template(_read_template_content())


def _read_template_content(template_name: str = "report.html") -> str:
    """Read template file content."""
    template_paths = [
        f"templates/{template_name}",
        os.path.join(os.path.dirname(__file__), "..", "templates", template_name),
    ]
    for tp in template_paths:
        if os.path.exists(tp):
            with open(tp, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(f"Could not find templates/{template_name}")


def generate_review_report(
    matched: list[dict],
    output_dir: str = "data/output",
    date_str: str | None = None,
    elo_changes: list[dict] | None = None,
    dimension_summary: str = "",
    pnl_text: str = "",
) -> str:
    """Generate review HTML report from matched predictions and results.

    Args:
        matched: list from result_fetcher.match_predictions_to_results()
        output_dir: output directory
        date_str: date string (defaults to today)
        elo_changes: optional list of {team, old, new, delta, reason}
        dimension_summary: 5维度复盘纯文本 (来自dimension_review)

    Returns:
        Path to generated HTML file
    """
    from datetime import date
    today = date_str or date.today().isoformat()
    out_path = os.path.join(output_dir, f"review_{today}.html")

    if not matched:
        os.makedirs(output_dir, exist_ok=True)
        html = f"<html><body><h1>No matched results for {today}</h1></body></html>"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return out_path

    n_total = len(matched)
    n_matched = sum(1 for m in matched if m.get("matched"))

    # ---- 评估指标 ----
    import math
    brier_sum = 0.0
    logloss_sum = 0.0
    correct = 0
    total_pl = 0.0
    n_bets = 0

    # 方向统计
    h_total = h_correct = 0
    d_total = d_correct = 0
    a_total = a_correct = 0

    match_rows = []
    for m in matched:
        pred = m["predicted"]
        actual = m["actual"]
        value = m.get("value") or {}
        home_goals = m.get("home_goals")
        away_goals = m.get("away_goals")

        # Brier: 三个结果的均方误差
        outcomes = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}
        actual_vec = outcomes.get(actual, [0, 0, 0])
        pred_vec = [pred["home_win"], pred["draw"], pred["away_win"]]
        brier_sum += sum((p - a) ** 2 for p, a in zip(pred_vec, actual_vec)) / 3

        # 对数损失: -ln(实际结果的概率)
        idx = {"H": 0, "D": 1, "A": 2}.get(actual, 0)
        p_actual = max(pred_vec[idx], 0.001)
        logloss_sum += -math.log(p_actual)

        # Accuracy
        best_pred = max(
            ("H", pred["home_win"]),
            ("D", pred["draw"]),
            ("A", pred["away_win"]),
            key=lambda x: x[1],
        )[0]
        if best_pred == actual:
            correct += 1

        # Directional
        if actual == "H":
            h_total += 1
            if best_pred == "H":
                h_correct += 1
        elif actual == "D":
            d_total += 1
            if best_pred == "D":
                d_correct += 1
        elif actual == "A":
            a_total += 1
            if best_pred == "A":
                a_correct += 1

        # 盈亏: 模拟最优方向1单位投注
        bet_dir = value.get("best_direction", "none")
        kelly = value.get("kelly", 0) or 0
        pl = 0.0
        # 投注方向映射到实际代码
        bet_to_actual = {"home": "H", "draw": "D", "away": "A"}
        if bet_dir != "none" and kelly > 0:
            n_bets += 1
            edge = value.get(f"{bet_dir}_edge", 0) or 0
            market_prob = pred_vec[{"home": 0, "draw": 1, "away": 2}[bet_dir]] - edge
            if market_prob > 0.01:
                odds = 1.0 / market_prob
                stake = kelly
                if bet_to_actual.get(bet_dir) == actual:
                    pl = stake * (odds - 1)
                else:
                    pl = -stake
            total_pl += pl

        # Match row
        pick_dir = value.get("best_direction", "none")
        if pick_dir == "home":
            pick = "H"
        elif pick_dir == "draw":
            pick = "D"
        elif pick_dir == "away":
            pick = "A"
        else:
            pick = best_pred

        if pick == actual:
            outcome = "hit"
            verdict = "✓ 命中"
        elif pick != best_pred and best_pred == actual:
            outcome = "push"
            verdict = "△ 走水"
        else:
            outcome = "miss"
            verdict = "✗ 失误"

        prob_pick = pred_vec[{"H": 0, "D": 1, "A": 2}.get(pick, 0)]

        home_cn, away_cn = _cn(m["home_team"], m["away_team"])
        match_rows.append({
            "home_team": home_cn,
            "away_team": away_cn,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "actual": actual,
            "pred_h": f"{pred['home_win']:.1%}",
            "pred_d": f"{pred['draw']:.1%}",
            "pred_a": f"{pred['away_win']:.1%}",
            "pred_pick_prob": f"{prob_pick:.1%}",
            "pick": pick,
            "outcome": outcome,
            "verdict": verdict,
            "pl": f"{pl:+.3f}u" if pl != 0 else None,
            "pl_class": "won" if pl > 0 else "lost" if pl < 0 else "",
            "cold_start": m.get("cold_start", False),
        })

    # Aggregate
    n = n_matched
    brier_val = round(brier_sum / n, 4) if n > 0 else 0
    logloss_val = round(logloss_sum / n, 4) if n > 0 else 0
    accuracy_val = correct / n if n > 0 else 0

    total_pl_val = round(total_pl, 2)
    roi_val = f"{total_pl / n_bets:+.1%}" if n_bets > 0 else "N/A"

    def _cls(v, low_good=True):
        if low_good:
            return "good" if v < 0.65 else "warn" if v < 0.70 else "bad"
        return "good" if v > 0.55 else "warn" if v > 0.45 else "bad"

    context = {
        "date": today,
        "n_total": n_total,
        "n_matched": n_matched,
        "brier": f"{brier_val:.4f}",
        "brier_class": _cls(brier_val),
        "logloss": f"{logloss_val:.4f}",
        "logloss_class": _cls(logloss_val * 0.9),
        "accuracy": f"{accuracy_val:.1%}",
        "accuracy_class": _cls(1 - accuracy_val, low_good=False),
        "total_pl": f"{total_pl_val:+.2f}u",
        "pl_class": "good" if total_pl_val > 0 else "bad" if total_pl_val < 0 else "",
        "roi": roi_val,
        "roi_class": "good" if total_pl_val > 0 else "bad",
        "h_correct": h_correct, "h_total": h_total,
        "h_rate": f"{h_correct/h_total:.1%}" if h_total > 0 else "N/A",
        "d_correct": d_correct, "d_total": d_total,
        "d_rate": f"{d_correct/d_total:.1%}" if d_total > 0 else "N/A",
        "a_correct": a_correct, "a_total": a_total,
        "a_rate": f"{a_correct/a_total:.1%}" if a_total > 0 else "N/A",
        "h_pct": round(h_total / n * 100) if n > 0 else 33,
        "d_pct": round(d_total / n * 100) if n > 0 else 34,
        "a_pct": round(a_total / n * 100) if n > 0 else 33,
        "matches": match_rows,
        "elo_changes": elo_changes or [],
        "dimension_summary": dimension_summary,
        "pnl_text": pnl_text,
    }

    # Render
    template = _get_review_template()
    html = template.render(**context)

    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] 复盘报告已保存 → {out_path}")
    return out_path


def _get_review_template():
    """Lazy-load review Jinja2 template."""
    try:
        from jinja2 import Template as Jinja2Template
    except ImportError:
        return _SimpleTemplate(_read_template_content("review.html"))
    return Jinja2Template(_read_template_content("review.html"))


def update_tracking_file(
    matched: list[dict],
    date_str: str,
    output_dir: str = "data/output",
    elo_summary: dict | None = None,
) -> dict:
    """Append daily review results to cumulative tracking file.

    Args:
        matched: matched predictions and results
        date_str: date of predictions
        output_dir: output directory
        elo_summary: optional ELO change summary

    Returns:
        Updated tracking data dict
    """
    tracking_path = os.path.join(output_dir, "daily_tracking.json")

    # Load existing
    if os.path.exists(tracking_path):
        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)
    else:
        tracking = {"days": [], "cumulative": {}}

    # 计算当日指标 (Phase 1 A2: 无信号场次不计入)
    sig = [m for m in matched if not m.get("no_signal")]
    n = len(sig)
    if n == 0:
        return tracking

    correct = 0
    brier_sum = 0.0
    for m in sig:
        pred = m["predicted"]
        actual = m["actual"]
        outcomes = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}
        actual_vec = outcomes.get(actual, [0, 0, 0])
        pred_vec = [pred["home_win"], pred["draw"], pred["away_win"]]
        brier_sum += sum((p - a) ** 2 for p, a in zip(pred_vec, actual_vec)) / 3

        best_pred = max(
            ("H", pred["home_win"]),
            ("D", pred["draw"]),
            ("A", pred["away_win"]),
            key=lambda x: x[1],
        )[0]
        if best_pred == actual:
            correct += 1

    day_entry = {
        "date": date_str,
        "matches": n,
        "no_signal_count": len(matched) - n,
        "brier": round(brier_sum / n, 4),
        "accuracy": round(correct / n, 4),
        "cold_start_count": sum(1 for m in sig if m.get("cold_start")),
    }

    if elo_summary:
        day_entry["elo_updates"] = elo_summary.get("teams_updated", 0)

    # 同日记录替换, 否则追加
    existing_idx = None
    for i, d in enumerate(tracking["days"]):
        if d.get("date") == date_str:
            existing_idx = i
            break
    if existing_idx is not None:
        tracking["days"][existing_idx] = day_entry
    else:
        tracking["days"].append(day_entry)

    # 更新累计值
    all_n = sum(d["matches"] for d in tracking["days"])
    all_brier = sum(d["brier"] * d["matches"] for d in tracking["days"]) / all_n if all_n > 0 else 0
    all_acc = sum(d["accuracy"] * d["matches"] for d in tracking["days"]) / all_n if all_n > 0 else 0
    tracking["cumulative"] = {
        "total_days": len(tracking["days"]),
        "total_matches": all_n,
        "avg_brier": round(all_brier, 4),
        "avg_accuracy": round(all_acc, 4),
    }

    with open(tracking_path, "w", encoding="utf-8") as f:
        json.dump(tracking, f, ensure_ascii=False, indent=2)

    print(f"[OK] 跟踪已更新: {tracking['cumulative']}")
    return tracking


class _SimpleTemplate:
    """Minimal Jinja2-free template renderer.

    Supports: {{ var }}, {% if var %}...{% endif %}, {% for m in list %}...{% endfor %}
    Used as fallback when jinja2 is not installed.
    """
    def __init__(self, source: str):
        import re
        self.source = source
        self._token_re = re.compile(
            r'(\{%\s*if\s+(\w+(?:\.\w+)*)\s*%\})'
            r'|(\{%\s*else\s*%\})'
            r'|(\{%\s*endif\s*%\})'
            r'|(\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\})'
            r'|(\{%\s*endfor\s*%\})'
            r'|(\{\{\s*(\w+(?:\.\w+(?:\(\))?)?)\s*\}\})'
        )

    def render(self, **context) -> str:
        return self._render_block(self.source, context)

    def _render_block(self, template: str, context: dict) -> str:
        import re as _re
        result = []

        # Tokenize
        tokens = _re.split(
            r'(\{%[^%]*%\}|\{\{[^}]*\}\})',
            template,
        )

        # 基于栈的解析
        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("{% if ") and token.endswith(" %}"):
                var_name = token[6:-3].strip()
                condition = self._resolve(var_name, context)
                # 查找匹配的endif/else
                depth = 1
                j = i + 1
                else_idx = -1
                endif_idx = -1
                while j < len(tokens):
                    t = tokens[j]
                    if t.startswith("{% if "):
                        depth += 1
                    elif t.startswith("{% endif %}"):
                        depth -= 1
                        if depth == 0:
                            endif_idx = j
                            break
                    elif t.startswith("{% else %}") and depth == 1:
                        else_idx = j
                    j += 1

                if condition:
                    start = i + 1
                    end = else_idx if else_idx >= 0 else endif_idx
                    block = "".join(tokens[start:end])
                    result.append(self._render_block(block, context))
                elif else_idx >= 0:
                    start = else_idx + 1
                    block = "".join(tokens[start:endif_idx])
                    result.append(self._render_block(block, context))
                i = endif_idx + 1

            elif token.startswith("{% for ") and token.endswith(" %}"):
                # 解析: for ITEM in LIST
                m = _re.match(r'\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}', token)
                if m:
                    item_name = m.group(1)
                    list_name = m.group(2)
                    items = context.get(list_name, [])
                    # 查找匹配的endfor
                    depth = 1
                    j = i + 1
                    while j < len(tokens):
                        t = tokens[j]
                        if t.startswith("{% for "):
                            depth += 1
                        elif t.startswith("{% endfor %}"):
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    block_tokens = tokens[i + 1:j]
                    block_src = "".join(block_tokens)
                    for item in items:
                        item_ctx = dict(context)
                        item_ctx[item_name] = item
                        result.append(self._render_block(block_src, item_ctx))
                    i = j + 1
                else:
                    i += 1

            elif token.startswith("{% else %}") or token.startswith("{% endif %}") or token.startswith("{% endfor %}"):
                i += 1

            elif token.startswith("{{ ") and token.endswith(" }}"):
                var_name = token[3:-3].strip()
                val = self._resolve(var_name, context)
                result.append(str(val) if val is not None else "")
                i += 1

            else:
                result.append(token)
                i += 1

        return "".join(result)

    def _resolve(self, var_path: str, context: dict) -> Any:
        """Resolve a dotted variable path like 'm.home_team' or 'backtest_brier'."""
        parts = var_path.split(".")
        val = context
        for part in parts:
            if val is None:
                return None
            if isinstance(val, dict):
                val = val.get(part)
            elif hasattr(val, part):
                val = getattr(val, part)
            else:
                return None
        return val


def _load_backtest_brier(output_dir: str) -> float | None:
    """Load backtest Brier score from report."""
    brier_path = os.path.join(output_dir, "backtest_report.json")
    if not os.path.exists(brier_path):
        return None
    try:
        with open(brier_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        return report.get("summary", {}).get("avg_brier")
    except Exception:
        return None
