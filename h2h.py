# -*- coding: utf-8 -*-
"""本地全库构建 + 历史交锋查询 (H2H)

数据源 (全部本地, 按联赛区分):
  - data/historical_odds/*.csv   Football-Data.co.uk 欧联赛 (英超/西甲/德甲/意甲/法甲/荷甲/葡超/比甲/土超/希超/苏冠...)
  - data/historical_odds/*.txt   openfootball 文本 (巴甲/巴乙/巴西杯/日职/瑞典/挪威/芬兰, 含杯赛)
  - data/openfootball_matches.json  历史解析产物 (巴甲/日职/北欧, 与txt去重)

产物: data/local_match_db.json — 统一schema全库
用法:
  python h2h.py --rebuild               # 重建本地全库
  python h2h.py "Benfica" "Porto"       # 查两队直接交锋 (近10场)
  python h2h.py --append 赛果.json       # 回灌每日复盘赛果到全库
  python h2h.py --stats                 # 按联赛统计全库
"""
import csv
import io
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DB_PATH = Path("data/local_match_db.json")
HIST_DIR = Path("data/historical_odds")

# = 联赛标题 → (代码, 中文名) — txt文件按标题行区分联赛
SECTION_MAP = [
    (re.compile(r"Brasileiro S[ée]rie A"), "BSA", "巴甲"),
    (re.compile(r"Brasileiro S[ée]rie B"), "BSB", "巴乙"),
    (re.compile(r"Copa do Brasil"), "CDB", "巴西杯"),
    (re.compile(r"J1 League"), "J1", "日职联"),
    (re.compile(r"Allsvenskan"), "SWE", "瑞典超"),
    (re.compile(r"Div 1 S[öo]dra"), "SWE3", "瑞典第三级南区"),
    (re.compile(r"Eliteserien"), "NOR", "挪超"),
    (re.compile(r"Norway Cupen"), "NORC", "挪威杯"),
    (re.compile(r"Veikkausliiga"), "FIN", "芬超"),
]

# CSV联赛代码 → 中文名
CSV_LEAGUE_CN = {
    "PL": "英超", "ELC": "英冠", "BPL": "比甲", "BR1": "比甲", "BS1": "比乙",
    "PD": "西甲", "PD2": "西乙", "BL1": "德甲", "BL2": "德乙",
    "SA": "意甲", "SB": "意乙", "FL1": "法甲", "FL2": "法乙",
    "DED": "荷甲", "PPL": "葡超", "SPL": "苏冠", "TUR": "土超", "GRE": "希超",
    "NO1": "挪威(CSV)",
}
LEAGUE_CN = {code: name for _, code, name in SECTION_MAP}
LEAGUE_CN.update(CSV_LEAGUE_CN)

MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
DATE_RE = re.compile(r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w{3})\s+(\d{1,2})\s+(\d{4})")
MATCH_RE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s+)?(?P<h>.+?)\s+v\s+(?P<a>.+?)\s+(?P<s>\d+\s*-\s*\d+)(?P<tail>.*)$")
SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _parse_txt_file(path: Path) -> list:
    """解析openfootball txt: 标题行定联赛, 日期行定比赛日, 比赛行含加时/点球处理"""
    from pipeline.data_loader import normalize_team_name

    league_code, league_name, season = "UNK", path.stem, None
    cur_date, matches = None, []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("="):  # 联赛标题
            for rx, code, name in SECTION_MAP:
                if rx.search(line):
                    league_code, league_name = code, name
                    m = re.search(r"(\d{4})", line)
                    season = m.group(1) if m else None
                    break
            continue
        if line.startswith(("#", "▪", "▫")):
            continue
        dm = DATE_RE.match(line)
        if dm:  # 比赛日
            cur_date = f"{dm.group(3)}-{MONTHS.get(dm.group(1), 1):02d}-{int(dm.group(2)):02d}"
            continue
        mm = MATCH_RE.match(line)
        if not mm:
            continue
        hg_str, ag_str = mm.group("s").split("-")
        # 加时/点球场次: 括号内首个比分为90分钟常规赛果
        tail = mm.group("tail")
        if "pen." in tail or "a.e.t." in tail:
            paren = SCORE_RE.search(tail.split("(")[-1] if "(" in tail else "")
            if paren:
                hg_str, ag_str = paren.group(1), paren.group(2)
        hg, ag = int(hg_str), int(ag_str)
        matches.append({
            "date": cur_date or "",
            "league_code": league_code,
            "league_name": league_name,
            "season": season,
            "home_team": normalize_team_name(mm.group("h").strip()),
            "away_team": normalize_team_name(mm.group("a").strip()),
            "home_goals": hg, "away_goals": ag,
            "result": "H" if hg > ag else "D" if hg == ag else "A",
            "source": "openfootball_txt",
        })
    return matches


def _load_csv_matches() -> list:
    """Football-Data.co.uk CSV → 统一schema"""
    from pipeline.data_loader import load_all_csvs
    out = []
    for m in load_all_csvs():
        out.append({
            "date": m["date"],
            "league_code": m["league_code"],
            "league_name": LEAGUE_CN.get(m["league_code"], m["league_code"]),
            "season": m["season"],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "home_goals": m["home_goals"],
            "away_goals": m["away_goals"],
            "result": m["result"],
            "source": "football_data_csv",
        })
    return out


def _load_openfootball_json() -> list:
    """历史openfootball JSON → 统一schema (与txt去重, txt联赛更精确优先)"""
    from pipeline.data_loader import normalize_team_name
    p = Path("data/openfootball_matches.json")
    if not p.exists():
        return []
    out = []
    for m in json.loads(p.read_text(encoding="utf-8")):
        hg, ag = m.get("home_goals") or 0, m.get("away_goals") or 0
        out.append({
            "date": m["date"],
            "league_code": m["league_code"],
            "league_name": LEAGUE_CN.get(m["league_code"], m["league_code"]),
            "season": m.get("season"),
            "home_team": normalize_team_name(m["home_team"]),
            "away_team": normalize_team_name(m["away_team"]),
            "home_goals": hg,
            "away_goals": ag,
            "result": "H" if hg > ag else "D" if hg == ag else "A",
            "source": "openfootball_json",
        })
    return out


def build_db() -> dict:
    """合并三源 → 去重 → 写 data/local_match_db.json"""
    seen, matches = set(), []
    # txt优先(联赛标注最精确), 其次CSV, 最后JSON
    for m in _parse_txt_all() + _load_csv_matches() + _load_openfootball_json():
        key = (m["date"], m["home_team"], m["away_team"])
        if key in seen:
            continue
        seen.add(key)
        matches.append(m)
    matches.sort(key=lambda x: x["date"])
    db = {"built": "2026-08-13", "total": len(matches), "matches": matches}
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    return db


def _parse_txt_all() -> list:
    out = []
    for f in sorted(HIST_DIR.glob("*.txt")):
        out.extend(_parse_txt_file(f))
    return out


def load_db() -> list:
    """读取全库 (不存在则自动重建)"""
    if not DB_PATH.exists():
        build_db()
    return json.loads(DB_PATH.read_text(encoding="utf-8"))["matches"]


def _team_match(a: str, b: str) -> bool:
    """队名匹配: 先精确, 再双向子串 (处理SE Palmeiras / Corinthians Paulista等前后缀)"""
    a = a.lower().replace(" ", "").replace(".", "").replace("'", "")
    b = b.lower().replace(" ", "").replace(".", "").replace("'", "")
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return a in b or b in a
    return False


def get_h2h(home: str, away: str, n: int = 10) -> tuple:
    """查两队直接交锋 → (交锋列表[按日期倒序], 两队全库出场数)"""
    from pipeline.data_loader import normalize_team_name
    home_n, away_n = normalize_team_name(home), normalize_team_name(away)
    db = load_db()
    h2h, h_cnt, a_cnt = [], 0, 0
    for m in db:
        h, a = m["home_team"], m["away_team"]
        if _team_match(home_n, h) and _team_match(away_n, a):
            h2h.append(m)
        elif _team_match(home_n, a) and _team_match(away_n, h):
            h2h.append(m)
        if _team_match(home_n, h) or _team_match(home_n, a):
            h_cnt += 1
        if _team_match(away_n, h) or _team_match(away_n, a):
            a_cnt += 1
    h2h.sort(key=lambda x: x["date"], reverse=True)
    return h2h[:n], h_cnt, a_cnt


def append_results(results_file: str) -> int:
    """回灌复盘赛果: 联赛从全库反查主队最近联赛, 查不到标UNK"""
    from pipeline.data_loader import normalize_team_name
    raw = json.loads(Path(results_file).read_text(encoding="utf-8"))
    db = load_db()
    team_league = {}
    for m in db:  # 主队最近一次出场联赛
        team_league[m["home_team"]] = m["league_code"]
        team_league[m["away_team"]] = m["league_code"]
    added = 0
    for r in raw:
        h = normalize_team_name(r.get("home_team", ""))
        a = normalize_team_name(r.get("away_team", ""))
        hg, ag = r.get("home_goals"), r.get("away_goals")
        if not h or not a or hg is None or ag is None:
            continue
        lc = team_league.get(h, "UNK")
        db.append({
            "date": r.get("date", ""), "league_code": lc,
            "league_name": LEAGUE_CN.get(lc, lc), "season": None,
            "home_team": h, "away_team": a,
            "home_goals": int(hg), "away_goals": int(ag),
            "result": "H" if hg > ag else "D" if hg == ag else "A",
            "source": "复盘回灌",
        })
        added += 1
    out = {"built": "2026-08-13", "total": len(db), "matches": db}
    DB_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return added


def print_h2h(home: str, away: str, n: int = 10):
    """终端输出交锋记录 (中文)"""
    h2h, h_cnt, a_cnt = get_h2h(home, away, n)
    print(f"\n⚔️ {home} vs {away} — 本地全库直接交锋")
    if not h2h:
        print(f"  本地无两队直接交锋记录 (常见原因: 跨国对决/杯赛/覆盖外联赛)")
        print(f"  全库出场: {home} {h_cnt}场 · {away} {a_cnt}场"
              + ("" if h_cnt and a_cnt else " → 至少一队不在本地覆盖范围"))
        return
    w = d = l = 0
    for m in h2h:
        hg, ag = m["home_goals"], m["away_goals"]
        if _team_match(home, m["home_team"]):
            if hg > ag:
                w += 1
            elif hg == ag:
                d += 1
            else:
                l += 1
            side = f"{m['home_team']} {hg}-{ag} {m['away_team']}"
        else:
            if ag > hg:
                w += 1
            elif ag == hg:
                d += 1
            else:
                l += 1
            side = f"{m['away_team']} {ag}-{hg} {m['home_team']}"
        print(f"  {m['date']} [{LEAGUE_CN.get(m['league_code'], m['league_code'])}] {side}")
    print(f"  {home}视角近{len(h2h)}场: {w}胜{d}平{l}负")


def print_stats():
    """按联赛统计全库"""
    db = load_db()
    by_league = defaultdict(int)
    for m in db:
        by_league[m["league_code"]] += 1
    print(f"\n📚 本地全库: {len(db)}场, 按联赛分布:")
    for code, cnt in sorted(by_league.items(), key=lambda x: -x[1]):
        print(f"  {code:6s} {LEAGUE_CN.get(code, '?'):10s} {cnt}场")


def main():
    args = [a for a in sys.argv[1:] if a != "--"]
    if "--rebuild" in sys.argv:
        db = build_db()
        print(f"✅ 全库重建完成: {db['total']}场 → {DB_PATH}")
        print_stats()
    elif "--append" in sys.argv:
        f = args[args.index("--append") + 1] if "--append" in args and len(args) > 1 else None
        if not f:
            print("用法: python h2h.py --append 赛果.json")
            return
        n = append_results(f)
        print(f"✅ 已回灌 {n} 场赛果到本地全库")
    elif "--stats" in sys.argv:
        print_stats()
    elif len(args) >= 2:
        print_h2h(args[0], args[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
