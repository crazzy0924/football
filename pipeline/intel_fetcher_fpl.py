# -*- coding: utf-8 -*-
"""
英超伤停情报采集 · 官方 Fantasy Premier League API (免费, 无 key)
==================================================================
数据源: https://fantasy.premierleague.com/api/bootstrap-static/
  - teams: 20 队 (id/name/short_name)
  - elements: 全球员 (team/web_name/news/chance_of_playing_next_round)
  - news 非空 = 伤停/停赛/转会/出战成疑; chance < 100 = 出场概率打折

输出: data/intel/fpl_YYYY-MM-DD.txt (独立文件, 由 analysis_page.py 合并进证据账本)
只覆盖英超(league_code=PL)场次; 其它联赛跳过 (五大里仅英超有官方免费结构化伤停)。

用法: python pipeline/intel_fetcher_fpl.py [YYYY-MM-DD]
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FPL_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

_ALIAS = {
    "arsenal": "Arsenal", "aston villa": "Aston Villa", "bournemouth": "Bournemouth",
    "brentford": "Brentford", "brighton": "Brighton", "brighton & hove albion": "Brighton",
    "chelsea": "Chelsea", "coventry": "Coventry City", "coventry city": "Coventry City",
    "crystal palace": "Crystal Palace", "everton": "Everton", "fulham": "Fulham",
    "hull": "Hull City", "hull city": "Hull City",
    "ipswich": "Ipswich Town", "ipswich town": "Ipswich Town",
    "leeds": "Leeds", "leeds united": "Leeds",
    "liverpool": "Liverpool",
    "man city": "Man City", "manchester city": "Man City",
    "man utd": "Man Utd", "man united": "Man Utd", "manchester united": "Man Utd", "manchester utd": "Man Utd",
    "newcastle": "Newcastle", "newcastle united": "Newcastle",
    "nott'm forest": "Nott'm Forest", "nottingham forest": "Nott'm Forest", "nottm forest": "Nott'm Forest",
    "spurs": "Spurs", "tottenham": "Spurs", "tottenham hotspur": "Spurs",
    "sunderland": "Sunderland",
    "阿森纳": "Arsenal", "阿斯顿维拉": "Aston Villa", "伯恩茅斯": "Bournemouth",
    "布伦特福德": "Brentford", "布莱顿": "Brighton", "切尔西": "Chelsea",
    "考文垂": "Coventry City", "水晶宫": "Crystal Palace", "埃弗顿": "Everton",
    "富勒姆": "Fulham", "赫尔城": "Hull City", "伊普斯维奇": "Ipswich Town",
    "利兹联": "Leeds", "利兹": "Leeds", "利物浦": "Liverpool",
    "曼城": "Man City", "曼彻斯特城": "Man City", "曼联": "Man Utd", "曼彻斯特联": "Man Utd",
    "纽卡斯尔": "Newcastle", "纽卡斯尔联": "Newcastle",
    "诺丁汉森林": "Nott'm Forest", "热刺": "Spurs", "托特纳姆热刺": "Spurs",
    "桑德兰": "Sunderland",
}


def _fetch():
    try:
        import httpx
        with httpx.Client(timeout=25, follow_redirects=True) as c:
            r = c.get(FPL_URL, headers={"User-Agent": "football-model/1.0"})
        if r.status_code != 200:
            print("  [FPL] HTTP %d" % r.status_code)
            return None
        return r.json()
    except Exception as e:
        print("  [FPL] 拉取失败: %s" % e)
        return None


def _resolve(team_name, teams_by_name, teams_by_short):
    n = (team_name or "").strip()
    if not n:
        return None
    key = n.lower().replace(" ", "").replace("'", "")
    for alias, fpl in _ALIAS.items():
        if alias.replace(" ", "").replace("'", "") == key:
            return teams_by_name.get(fpl.lower())
    if n.lower() in teams_by_name:
        return teams_by_name[n.lower()]
    if n.upper() in teams_by_short:
        return teams_by_short[n.upper()]
    low = n.lower()
    for fpl_name, obj in teams_by_name.items():
        if fpl_name in low or low in fpl_name:
            return obj
    return None


def _chance_label(c):
    if c is None:
        return "未知"
    if c == 100:
        return "可出战"
    if c == 0:
        return "缺阵"
    return "出战成疑 %d%%" % c


def team_injuries(team_name, data, teams_by_name, teams_by_short):
    tobj = _resolve(team_name, teams_by_name, teams_by_short)
    if not tobj:
        return []
    tid = tobj["id"]
    items = []
    for e in data.get("elements", []):
        if e.get("team") != tid:
            continue
        news = (e.get("news") or "").strip()
        chance = e.get("chance_of_playing_next_round")
        if news or (chance is not None and chance < 100):
            wname = e.get("web_name") or e.get("second_name") or "?"
            reason = news if news else "状态存疑"
            items.append("%s (%s, %s)" % (wname, reason, _chance_label(chance)))
    return items


def build_intel(matches, max_matches=30):
    data = _fetch()
    if not data:
        return ""
    teams = data.get("teams", [])
    teams_by_name = {t["name"].lower(): t for t in teams}
    teams_by_short = {t.get("short_name", "").upper(): t for t in teams}

    lines = ["=== 英超伤停/状态 (FPL 官方 API · 免费) ==="]
    hit = 0
    for m in matches[:max_matches]:
        if (m.get("league_code") or "").upper() != "PL":
            continue
        home = m.get("home_team") or m.get("home") or ""
        away = m.get("away_team") or m.get("away") or ""
        if not home or not away:
            continue
        hit += 1
        lines.append("[%s vs %s]" % (home, away))
        for tn in (home, away):
            obj = _resolve(tn, teams_by_name, teams_by_short)
            fpl_name = (obj or {}).get("name", tn)
            inj = team_injuries(tn, data, teams_by_name, teams_by_short)
            if inj:
                lines.append("  %s伤停: %s" % (fpl_name, "; ".join(inj[:8])))
            else:
                lines.append("  %s: 无公开伤停标记" % fpl_name)
        lines.append("")
    if hit == 0:
        return ""
    lines.append("(来源: fantasy.premierleague.com 官方 API, 采集于 %s, 仅英超)" % date.today().isoformat())
    return "\n".join(lines)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    today_path = os.path.join("data", "today.json")
    if not os.path.exists(today_path):
        print("未找到 data/today.json")
        return
    with open(today_path, "r", encoding="utf-8") as f:
        matches = json.load(f)
    pl_count = sum(1 for m in matches if (m.get("league_code") or "").upper() == "PL")
    if pl_count == 0:
        print("今日无英超场次, 跳过 FPL 采集。")
        return
    print("FPL 伤停采集: %d 场英超..." % pl_count)
    intel_text = build_intel(matches)
    out_path = os.path.join("data", "intel", "fpl_%s.txt" % date_str)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write((intel_text or "") + "\n")
    if intel_text:
        print("已写入 → %s" % out_path)
        print(intel_text[:600])
    else:
        print("未采集到 FPL 伤停信息。")


if __name__ == "__main__":
    main()
