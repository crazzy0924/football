# -*- coding: utf-8 -*-
"""从 SofaScore 抓取逐场 xG (预期进球), 建立可回溯的 xG 数据集。

为什么用 SofaScore 而不是 StatsBomb 开放数据:
  2026-09-14 实测 —— 开放数据最新五大赛季只到 23/24 且只有 34 场, 零当季;
  而 SofaScore 当季五大联赛抽 10 场 10/10 都带 xG, 且历史可回溯到 22/23。
  抓取框架(Playwright+Edge 过反爬 / 限速 / 青年队过滤)本仓库已有, 属增量工作。

数据只作训练/研究用, 不进入预测的必选链路 —— 是否采用由配对检验决定
(见 CLAUDE.md 第十一节: xG 版 DC vs 现版 DC, 逐场 Brier 差的 t 值 > 2 才纳入)。

用法:
    python pipeline/xg_fetcher.py --limit 8          # 小样验证通道
    python pipeline/xg_fetcher.py                    # 全量 (5 赛季 x 五大, 约 35~40 分钟)
    python pipeline/xg_fetcher.py --leagues PL,PD --seasons 26
断点续抓: 每抓完一场立刻落盘, 重跑会自动跳过已有场次。
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 注意: 这里必须用 reconfigure 而不是 sys.stdout = io.TextIOWrapper(...)。
# 下面导入的 odds_fetcher_sofascore 模块自己也会重新包装 stdout —— 如果这边先包一层,
# 那一层就失去引用被 GC, 其 __del__ 会把底层 buffer 关掉, 后续所有 print 报
# "I/O operation on closed file"。reconfigure 不产生新对象, 没有这个坑。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline.odds_fetcher_sofascore import (  # noqa: E402
    API, TOURNAMENTS, is_youth_or_reserve,
)

OUT_DIR = os.path.join("data", "state", "xg")
# xG 回溯起点: SofaScore 从 22/23 起才有 (20/21、21/22 实测没有)
SEASON_YEARS = ["22", "23", "24", "25", "26"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _j(pg, url, tries: int = 3):
    """在页面上下文里走 JS fetch (同源, 绕开反爬), 失败重试。"""
    for k in range(tries):
        try:
            r = pg.evaluate(
                """async (u) => {
                    try {
                        const r = await fetch(u, {headers: {'accept': 'application/json'}});
                        if (!r.ok) return {__status: r.status};
                        return await r.json();
                    } catch (e) { return {__err: String(e)}; }
                }""", url)
            if isinstance(r, dict) and r.get("__status") == 404:
                return None
            if isinstance(r, dict) and (r.get("__err") or r.get("__status")):
                time.sleep(1.5 * (k + 1))
                continue
            return r
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def find_xg(stats) -> tuple[float | None, float | None]:
    """在统计树里递归找 'Expected goals', 返回 (主队, 客队)。"""
    hit = {}

    def walk(node):
        if hit:
            return
        if isinstance(node, dict):
            if str(node.get("name", "")).strip().lower() == "expected goals":
                hv, av = node.get("homeValue"), node.get("awayValue")
                if hv is None:
                    try:
                        hv = float(node.get("home"))
                    except (TypeError, ValueError):
                        hv = None
                if av is None:
                    try:
                        av = float(node.get("away"))
                    except (TypeError, ValueError):
                        av = None
                if hv is not None and av is not None:
                    hit["h"], hit["a"] = float(hv), float(av)
                    return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(stats)
    return hit.get("h"), hit.get("a")


def season_list(pg, tid: int) -> list[dict]:
    r = _j(pg, "%s/unique-tournament/%d/seasons" % (API, tid))
    return (r or {}).get("seasons") or []


def season_matches(pg, tid: int, sid: int, cap_pages: int = 40) -> list[dict]:
    """整季赛程。events/last/{page} 按页倒序取, 直到空页。"""
    out, page = [], 0
    while page < cap_pages:
        r = _j(pg, "%s/unique-tournament/%d/season/%d/events/last/%d" % (API, tid, sid, page))
        evs = (r or {}).get("events") or []
        if not evs:
            break
        out.extend(evs)
        if not (r or {}).get("hasNextPage"):
            break
        page += 1
        time.sleep(0.3)
    return out


def load_one(code: str, season: str) -> dict:
    p = os.path.join(OUT_DIR, "%s_%s.json" % (code, season))
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_one(code: str, season: str, doc: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "%s_%s.json" % (code, season))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="", help="逗号分隔, 默认五大+欧冠")
    ap.add_argument("--seasons", default="", help="赛季起始年两位, 逗号分隔, 默认 22~26")
    ap.add_argument("--limit", type=int, default=0, help="每联赛-赛季最多抓 N 场 (验证通道)")
    ap.add_argument("--delay", type=float, default=0.3, help="每场之间的间隔秒")
    a = ap.parse_args()

    want_lg = {x.strip().upper() for x in a.leagues.split(",") if x.strip()}
    want_sn = [x.strip() for x in a.seasons.split(",") if x.strip()] or SEASON_YEARS
    tours = [t for t in TOURNAMENTS if not want_lg or t[1] in want_lg]
    os.makedirs(OUT_DIR, exist_ok=True)

    from playwright.sync_api import sync_playwright
    grand_new = grand_have = grand_noxg = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="msedge")
        pg = b.new_context(user_agent=UA).new_page()
        pg.goto("https://www.sofascore.com/football", timeout=60000, wait_until="domcontentloaded")
        pg.wait_for_timeout(2500)

        for tid, code, name in tours:
            seasons = season_list(pg, tid)
            if not seasons:
                print("[%s] 取不到赛季列表, 跳过" % code)
                continue
            for y in want_sn:
                cand = [s for s in seasons if str(s.get("year", "")).startswith(y)]
                if not cand:
                    continue
                sid = cand[0]["id"]
                season = y + "-" + str(int(y) + 1)
                doc = load_one(code, season)
                if "matches" not in doc:
                    doc = {"league": code, "season": season, "season_id": sid, "matches": {}}
                evs = season_matches(pg, tid, sid)
                todo = []
                for e in evs:
                    h = (e.get("homeTeam") or {}).get("name") or ""
                    aw = (e.get("awayTeam") or {}).get("name") or ""
                    if is_youth_or_reserve(h, aw):
                        continue
                    st = (e.get("status") or {}).get("type")
                    if st != "finished":
                        continue
                    if str(e["id"]) in doc["matches"]:
                        grand_have += 1
                        continue
                    todo.append(e)
                if a.limit:
                    todo = todo[:a.limit]
                print("[%s %s] 赛事 %d 场, 已存 %d, 待抓 %d" % (
                    code, season, len(evs), len(doc["matches"]), len(todo)))
                for i, e in enumerate(todo, 1):
                    st = _j(pg, "%s/event/%d/statistics" % (API, e["id"]))
                    xh, xa = find_xg(st) if st else (None, None)
                    h = (e.get("homeTeam") or {}).get("name") or ""
                    aw = (e.get("awayTeam") or {}).get("name") or ""
                    hs = ((e.get("homeScore") or {}).get("current"))
                    as_ = ((e.get("awayScore") or {}).get("current"))
                    rec = {"date": (e.get("startTimestamp") and
                                    time.strftime("%Y-%m-%d", time.gmtime(e["startTimestamp"]))),
                           "home": h, "away": aw, "hg": hs, "ag": as_,
                           "xg_h": xh, "xg_a": xa}
                    if xh is None:
                        grand_noxg += 1
                    else:
                        grand_new += 1
                    doc["matches"][str(e["id"])] = rec
                    if i % 10 == 0 or i == len(todo):
                        save_one(code, season, doc)
                        print("    %d/%d  (有xG %d)" % (i, len(todo), grand_new))
                    time.sleep(a.delay)
                save_one(code, season, doc)
                got = sum(1 for v in doc["matches"].values() if v.get("xg_h") is not None)
                print("  → %s %s 共 %d 场, 含 xG %d (%.0f%%)" % (
                    code, season, len(doc["matches"]), got,
                    got / max(len(doc["matches"]), 1) * 100))
        b.close()

    print()
    print("完成: 新增 %d 场(有xG) / 跳过已有 %d 场 / 无xG %d 场" % (grand_new, grand_have, grand_noxg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
