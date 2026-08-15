# -*- coding: utf-8 -*-
"""
五大联赛积分榜采集 (Phase 7 · 2026-08-16)

football-data.org v4 /standings → 每队排名/积分/近5场形态
用法:
  python pipeline/standings_fetcher.py [season]

产物: data/state/standings.json
  {league_code: {team_name_cleaned: {pos, points, form}}}
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import FOOTBALL_DATA_API_KEY, FOCUS_LEAGUES  # noqa: E402

COMP_CODES = ["PL", "PD", "BL1", "SA", "FL1"]


def _clean(s: str) -> str:
    s = re.sub(r"[^a-z]", "", s.lower())
    return s


def fetch_standings(season: str | None = None) -> dict:
    """拉取聚焦联赛积分榜 → {code: {cleaned_name: {pos, points, form}}}"""
    if not FOOTBALL_DATA_API_KEY:
        print("未配置 FOOTBALL_DATA_API_KEY, 跳过积分榜采集。")
        return {}
    import httpx
    season = season or str(date.today().year)
    out: dict = {}
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    with httpx.Client(timeout=20) as c:
        for code in COMP_CODES:
            if code not in FOCUS_LEAGUES:
                continue
            try:
                r = c.get(
                    f"https://api.football-data.org/v4/competitions/{code}/standings",
                    params={"season": season},
                    headers=headers,
                )
            except Exception as e:
                print(f"  {code} 请求失败: {e}")
                continue
            if r.status_code != 200:
                print(f"  {code}: HTTP {r.status_code}")
                continue
            data = r.json()
            table = {}
            for st in data.get("standings", []):
                if st.get("type") != "TOTAL":
                    continue
                for row in st.get("table", []):
                    team = (row.get("team") or {}).get("name", "")
                    pos = row.get("position")
                    points = row.get("points")
                    form = row.get("form") or ""
                    if not team:
                        continue
                    table[_clean(team)] = {
                        "pos": pos, "points": points,
                        "form": form, "name": team,
                    }
            out[code] = table
            print(f"  {code}: {len(table)} 队")
    return out


def lookup(table: dict | None, team: str) -> dict | None:
    """按球队名查积分榜条目 (清洗后精确匹配, 退而求其次子串)"""
    if not table or not team:
        return None
    key = _clean(team)
    if key in table:
        return table[key]
    # 子串兜底: 队名互为子串 (如 Villarreal vs Villarreal CF)
    for k, v in table.items():
        if key and (key in k or k in key):
            return v
    return None


def main() -> None:
    # 仅在独立运行时包装 stdout (被导入时绝不包装, 避免与调用方冲突)
    if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    season = sys.argv[1] if len(sys.argv) > 1 else str(date.today().year)
    standings = fetch_standings(season)
    if not standings:
        print("未采集到积分榜。")
        return
    path = os.path.join("data", "state", "standings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(standings, f, ensure_ascii=False, indent=2)
    print(f"已保存 {sum(len(t) for t in standings.values())} 队积分榜 → {path}")


if __name__ == "__main__":
    main()
