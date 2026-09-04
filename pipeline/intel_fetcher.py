# -*- coding: utf-8 -*-
"""
API-Football 伤停情报采集 (Phase 6 · 2026-08-15)

自动采集当日比赛球队的伤停名单, 生成赛前情报文本 → data/intel/YYYY-MM-DD.txt
供 predict --llm 注入分析师证据包。

预算控制 (免费档 ~100 请求/天):
  - 队名→ID 查询永久缓存 (data/state/rapidapi_teams.json)
  - 伤停按日缓存 (同日不重复请求)
  - 每日硬上限 60 请求, 超限跳过
用法:
  python pipeline/intel_fetcher.py [YYYY-MM-DD]
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

from config import FOOTBALL_RAPIDAPI_KEY  # noqa: E402

API_HOST = "v3.football.api-sports.io"  # api-football.com 直连 (RapidAPI 页面在部分地区打不开, 改自家平台)
TEAM_CACHE = "data/state/rapidapi_teams.json"
INJ_CACHE = "data/state/rapidapi_injuries.json"
DAILY_BUDGET = 60

_requests_used = 0


def _get(path: str, params: dict) -> dict | None:
    """带预算的 API 请求"""
    global _requests_used
    if _requests_used >= DAILY_BUDGET:
        return None
    try:
        import httpx
        headers = {
            "x-apisports-key": FOOTBALL_RAPIDAPI_KEY,
        }
        _requests_used += 1
        with httpx.Client(timeout=15) as c:
            r = c.get(f"https://{API_HOST}{path}", params=params, headers=headers)
        if r.status_code == 429 or r.status_code == 403:
            print(f"  [限流/未订阅] {path}: HTTP {r.status_code}")
            return None
        if r.status_code != 200:
            print(f"  [警告] {path}: HTTP {r.status_code} {r.text[:100]}")
            return None
        data = r.json()
        if data.get("errors"):  # api-sports.io 对无效 key 也回 200 + errors 体
            return None
        return data
    except Exception as e:
        print(f"  [警告] 请求失败 {path}: {e}")
        return None


def _load_cache(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _team_id(name: str) -> int | None:
    """队名 → API-Football 球队ID (带永久缓存)"""
    cache = _load_cache(TEAM_CACHE)
    if name in cache:
        return cache[name]
    j = _get("/teams", {"search": name})
    teams = (j or {}).get("response", [])
    if not teams:
        cache[name] = None
        _save_cache(TEAM_CACHE, cache)
        return None
    tid = teams[0]["team"]["id"]
    nl = name.lower()
    for t in teams:
        tn = (t["team"].get("name") or "").lower()
        if nl in tn or tn in nl:
            tid = t["team"]["id"]
            break
    cache[name] = tid
    _save_cache(TEAM_CACHE, cache)
    return tid


def fetch_team_injuries(name: str) -> list[str]:
    """球队当前伤停 → [球员名(伤情/原因), ...] (按日缓存)"""
    inj_cache = _load_cache(INJ_CACHE)
    today = date.today().isoformat()
    ent = inj_cache.get(name)
    if ent and ent.get("date") == today:
        return ent.get("items", [])

    tid = _team_id(name)
    if not tid:
        return []
    season = date.today().year  # 当前赛季
    j = _get("/injuries", {"team": tid, "season": str(season)})
    items = []
    for inj in (j or {}).get("response", []):
        p = inj.get("player", {})
        pname = p.get("name", "?")
        ptype = inj.get("type") or p.get("type") or ""
        reason = inj.get("reason") or p.get("reason") or ""
        if ptype or reason:
            items.append(f"{pname} ({ptype}: {reason})")
        else:
            items.append(pname)

    inj_cache[name] = {"date": today, "items": items}
    _save_cache(INJ_CACHE, inj_cache)
    return items


def build_auto_intel(matches: list[dict], max_matches: int = 20) -> str:
    """为当日比赛生成情报文本"""
    lines = []
    done_teams: set[str] = set()
    for m in matches[:max_matches]:
        home = m.get("home_team") or m.get("home") or ""
        away = m.get("away_team") or m.get("away") or ""
        if not home or not away:
            continue
        parts = []
        for team in (home, away):
            if team in done_teams:
                continue
            done_teams.add(team)
            injuries = fetch_team_injuries(team)
            if injuries:
                parts.append(f"{team}伤停: " + "; ".join(injuries[:6]))
        if parts:
            lines.append(f"[{home} vs {away}]")
            lines.extend("  " + p for p in parts)
            lines.append("")
    return "\n".join(lines).strip()


def _check_key() -> bool:
    """预检密钥: 1个请求, 失败时给出明确提示 (避免403刷屏)"""
    try:
        import httpx
        headers = {
            "x-apisports-key": FOOTBALL_RAPIDAPI_KEY,
        }
        with httpx.Client(timeout=15) as c:
            r = c.get(f"https://{API_HOST}/status", headers=headers)
        if r.status_code == 200:
            j = r.json()
            if j.get("errors"):
                print("[密钥预检失败] key 无效或未订阅 — " + str(j.get("errors"))[:140])
                print("请确认: 1) 在 https://www.api-football.com/ 注册, Dashboard 里有 16 位 API key")
                print("        2) .env 里 FOOTBALL_RAPIDAPI_KEY 去掉开头的 # 并填入真实 key (现在是占位符 xxxxxxxx...)")
                return False
            resp = j.get("response") or {}
            acc = (resp.get("account") or {}).get("firstname", "?")
            sub = (resp.get("subscription") or {}).get("plan", "?")
            req = resp.get("requests") or {}
            print(f"[OK] API-Football 可用: 账户{acc}, 套餐{sub}, 今日 {req.get('current', '?')}/{req.get('limit_day', '?')}")
            return True
        if r.status_code == 403:
            print("[密钥预检失败] HTTP 403 — " + r.text[:120])
            return False
        print(f"[密钥预检失败] HTTP {r.status_code} — {r.text[:120]}")
        return False
    except Exception as e:
        print(f"[密钥预检失败] 网络异常: {e}")
        return False


def main() -> None:
    if not FOOTBALL_RAPIDAPI_KEY:
        print("未配置 FOOTBALL_RAPIDAPI_KEY, 跳过情报采集。")
        return

    if "--check" in sys.argv:
        _check_key()
        return

    if not _check_key():
        print("跳过情报采集 (密钥不可用)。")
        return

    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    today_path = os.path.join("data", "today.json")
    if not os.path.exists(today_path):
        print(f"未找到 {today_path}, 请先运行 fetch_sporttery.py")
        return
    with open(today_path, "r", encoding="utf-8") as f:
        matches = json.load(f)

    print(f"API-Football 情报采集: {len(matches)} 场比赛...")
    intel_text = build_auto_intel(matches)
    print(f"请求数: {_requests_used}/{DAILY_BUDGET}")

    intel_path = os.path.join("data", "intel", f"{date_str}.txt")
    os.makedirs(os.path.dirname(intel_path), exist_ok=True)
    with open(intel_path, "w", encoding="utf-8") as f:
        f.write(intel_text + "\n")
    if intel_text:
        print(f"已写入情报 → {intel_path}")
        print(intel_text[:400])
    else:
        print("未采集到伤停信息 (无伤停或球队未匹配)。")


if __name__ == "__main__":
    main()
