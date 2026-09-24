# -*- coding: utf-8 -*-
"""国家队语料加载 —— 数据源: martj42/international_results (全国际比赛 1872-今)。

产出 match dict 的统一 schema:
  date / home / away / hg / ag / tournament / neutral / comp (4 分类)
"""
import csv, os, sys
from datetime import date as _date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "national", "results.csv")
# 本地补录: 上游 martj42 仓库有 1-2 天延迟。万一某轮比赛结束后上游还没更新,
# 就把赛果手写进这个文件 (schema 与上游 CSV 完全一致), load_matches 会自动并进来。
# 这样"上游滞后"永远不会卡住我们。
OVERLAY_PATH = os.path.join(ROOT, "data", "national", "results_local.csv")

# ── 赛事重要度分组 ──
# 分组只用于两件事: (1) 主队优势按组估计; (2) 友谊赛降权。
# 友谊赛降权理由: 换人多、试验阵容、比分不代表真实实力。
FRIENDLY = "FRIENDLY"
NL = "NL"
QUAL = "QUAL"
FINALS = "FINALS"

FRIENDLY_WEIGHT = 0.65

_FINALS_KEYS = ["FIFA World Cup", "UEFA Euro", "Copa América", "African Cup of Nations",
                "AFC Asian Cup", "CONCACAF Gold Cup", "Gold Cup", "Oceania Nations Cup",
                "Confederations Cup", "UEFA Nations League finals"]


def classify(tournament: str) -> str:
    """把语料里的 tournament 字段归到 4 组之一。"""
    t = (tournament or "").strip()
    if t == "Friendly":
        return FRIENDLY
    if t == "UEFA Nations League":
        return NL
    if "qualification" in t.lower():
        return QUAL
    # 决赛圈: 名字里没有 qualification 的洲际/世界大赛
    for k in _FINALS_KEYS:
        if t == k:
            return FINALS
    return QUAL


def load_matches(since: str = "2016-01-01", until: str | None = None,
                 path: str | None = None) -> list[dict]:
    """读语料 (+ 本地补录 overlay) 并过滤到 [since, until] 区间。

    overlay 与主表按 (date, home, away) 去重, 主表优先。
    """
    p = path or CSV_PATH
    if not os.path.exists(p):
        raise FileNotFoundError("语料缺失: %s" % p)
    out = []
    for r in _iter_rows(p):
        d = r["date"]
        if d < since:
            continue
        if until and d > until:
            continue
        out.append({
            "date": d,
            "home": r["home_team"],
            "away": r["away_team"],
            "hg": int(float(r["home_score"])),
            "ag": int(float(r["away_score"])),
            "tournament": r.get("tournament", ""),
            "comp": classify(r.get("tournament", "")),
            "neutral": str(r.get("neutral", "")).strip().upper() in ("TRUE", "1"),
            "city": r.get("city", ""),
            "country": r.get("country", ""),
        })
    out.sort(key=lambda m: m["date"])
    return out


def _iter_rows(path: str):
    """依次吐出主表 + overlay 的行, 并做 (date, home, away) 去重 (主表优先)。"""
    seen = set()
    paths = [path]
    if path == CSV_PATH and os.path.exists(OVERLAY_PATH):
        paths.append(OVERLAY_PATH)
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                hs, as_ = r.get("home_score", ""), r.get("away_score", "")
                if hs == "" or as_ == "":
                    continue
                key = (r["date"], r["home_team"], r["away_team"])
                if key in seen:
                    continue
                seen.add(key)
                yield r


def days_between(d1: str, d2: str) -> int:
    y1, m1, dd1 = [int(x) for x in d1.split("-")]
    y2, m2, dd2 = [int(x) for x in d2.split("-")]
    return (_date(y2, m2, dd2) - _date(y1, m1, dd1)).days


def rest_days(matches: list[dict]) -> dict:
    """每支队在每场赛前的休息天数 (距上一场国际比赛)。首场为 None。

    用户 2026-09-24 明确要这个特征: 本届欧国联 9/24-10/6 是超长国际窗,
    各队要在 13 天里连打 4 场, 队与队之间的间隔差异是这次最可能的真实信号。
    """
    last: dict[str, str] = {}
    out = []
    for m in matches:
        rh = last.get(m["home"])
        ra = last.get(m["away"])
        m2 = dict(m)
        m2["rest_home"] = days_between(rh, m["date"]) if rh else None
        m2["rest_away"] = days_between(ra, m["date"]) if ra else None
        out.append(m2)
        last[m["home"]] = m["date"]
        last[m["away"]] = m["date"]
    return out


if __name__ == "__main__":
    ms = load_matches()
    print("语料:", len(ms), "场", ms[0]["date"], "->", ms[-1]["date"])
    from collections import Counter
    print(Counter(m["comp"] for m in ms))