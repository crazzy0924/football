# -*- coding: utf-8 -*-
"""
P&L 账本 (Phase 5 · 2026-08-15)

真实投注盈亏追踪:
  - 投注单: data/bets/bets_YYYY-MM-DD.json (手写或由交叉分析产出)
  - 结算: review 命令自动结算当日投注 → data/state/pnl_ledger.json
  - 幂等: 结算后投注单改名 bets_DATE.settled.json, 同日重跑 review 不会重复结算

维度方向约定:
  1X2:      "H" | "D" | "A"
  OU25/OU35: "over" | "under"
  BTTS:     "yes" | "no"
  AH:       "home" | "away" (需 line 字段; 走盘=退款)
"""
from __future__ import annotations

import json
import os
from typing import Any


def load_bets(date_str: str, bets_dir: str = "data/bets") -> list[dict] | None:
    """加载当日未结算投注单; 不存在返回 None"""
    path = os.path.join(bets_dir, f"bets_{date_str}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        bets = json.load(f)
    return bets if isinstance(bets, list) else None


def _find_result(bet: dict, matched: list[dict]) -> dict | None:
    """按球队名在已匹配赛果中查找对应比赛 (主客写反也容忍)"""
    bh = (bet.get("home_team") or "").lower().replace(" ", "")
    ba = (bet.get("away_team") or "").lower().replace(" ", "")
    for m in matched:
        mh = (m.get("home_team") or "").lower().replace(" ", "")
        ma = (m.get("away_team") or "").lower().replace(" ", "")
        if bh and bh in mh and ba and ba in ma:
            return m
        if bh and bh in ma and ba and ba in mh:
            return m
    return None


def _settle_one(bet: dict, m: dict) -> dict:
    """结算一注 → {status: win|loss|push|unsettled, payout, reason}"""
    gh = m.get("home_goals")
    ga = m.get("away_goals")
    if gh is None or ga is None:
        return {"status": "unsettled", "payout": 0.0, "reason": "赛果缺进球数"}
    dim = bet.get("dimension", "1X2")
    direction_raw = str(bet.get("direction", ""))
    direction = direction_raw.lower()
    total = gh + ga
    odds = float(bet.get("odds") or 0)
    stake = float(bet.get("stake") or 0)

    def finish(win: bool, push: bool, reason: str) -> dict:
        if push:
            return {"status": "push", "payout": round(stake, 2), "reason": reason}
        if win:
            return {"status": "win", "payout": round(stake * odds, 2), "reason": reason}
        return {"status": "loss", "payout": 0.0, "reason": reason}

    if dim == "1X2":
        actual = "H" if gh > ga else "D" if gh == ga else "A"
        return finish(direction == actual.lower(), False, f"赛果{gh}-{ga} {actual} vs 押{direction_raw}")
    if dim in ("OU25", "OU35"):
        line = 2.5 if dim == "OU25" else 3.5
        over = total > line
        big = "大" if over else "小"
        if direction == "over":
            return finish(over, False, f"总进球{total} {big}{line}")
        return finish(not over, False, f"总进球{total} {big}{line}")
    if dim == "BTTS":
        btts = gh > 0 and ga > 0
        txt = "双方进球" if btts else "未双方进球"
        if direction == "yes":
            return finish(btts, False, f"{gh}-{ga} {txt}")
        return finish(not btts, False, f"{gh}-{ga} {txt}")
    if dim == "AH":
        try:
            line = float(bet.get("line", 0))
        except (TypeError, ValueError):
            return {"status": "unsettled", "payout": 0.0, "reason": "AH 缺 line 字段"}
        diff = (gh - ga) + line
        push = abs(diff) < 1e-9
        if direction == "home":
            return finish(diff > 0, push, f"让球{line:+.1f} 净胜{gh-ga:+d}")
        return finish(diff < 0, push, f"让球{line:+.1f} 净胜{gh-ga:+d}")
    return {"status": "unsettled", "payout": 0.0, "reason": f"未知维度 {dim}"}


def settle_bets_for_date(
    date_str: str,
    matched: list[dict],
    state_dir: str = "data/state",
    bets_dir: str = "data/bets",
) -> dict | None:
    """结算当日投注并累计到账本; 无投注单返回 None"""
    bets = load_bets(date_str, bets_dir)
    if not bets:
        return None

    ledger_path = os.path.join(state_dir, "pnl_ledger.json")
    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    else:
        ledger = {
            "bets": [],
            "by_dimension": {},
            "cumulative": {"n": 0, "staked": 0.0, "return": 0.0, "roi": 0.0},
        }

    settled = []
    for bet in bets:
        m = _find_result(bet, matched)
        if m is None:
            settled.append({**bet, "status": "unsettled", "payout": 0.0, "reason": "未匹配到赛果"})
            continue
        res = _settle_one(bet, m)
        score = f"{m.get('home_goals')}-{m.get('away_goals')}"
        entry = {**bet, **res, "date": date_str, "score": score}
        settled.append(entry)
        ledger["bets"].append(entry)

        dim = bet.get("dimension", "1X2")
        D = ledger["by_dimension"].setdefault(
            dim, {"n": 0, "staked": 0.0, "return": 0.0, "roi": 0.0}
        )
        stake = float(bet.get("stake") or 0)
        D["n"] += 1
        D["staked"] = round(D["staked"] + stake, 2)
        D["return"] = round(D["return"] + entry["payout"], 2)
        D["roi"] = round((D["return"] - D["staked"]) / D["staked"], 4) if D["staked"] > 0 else 0.0

    C = ledger["cumulative"]
    settled_ok = [b for b in settled if b.get("status") != "unsettled"]
    day_staked = sum(float(b.get("stake") or 0) for b in settled_ok)
    day_return = sum(float(b.get("payout") or 0) for b in settled_ok)
    C["n"] += sum(1 for b in settled if b.get("status") != "unsettled")
    C["staked"] = round(C["staked"] + day_staked, 2)
    C["return"] = round(C["return"] + day_return, 2)
    C["roi"] = round((C["return"] - C["staked"]) / C["staked"], 4) if C["staked"] > 0 else 0.0

    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)

    # 幂等: 结算后投注单改名, 重跑 review 不会重复结算
    # 增量复盘保护: 有注未匹配到赛果时保留投注单, 等后续赛果到达再结算
    has_unsettled = any(b.get("status") == "unsettled" for b in settled)
    if has_unsettled:
        n_pending = sum(1 for b in settled if b.get('status') == 'unsettled')
        print(f"  [P&L] {n_pending} 注未匹配到赛果, 投注单保留待后续复盘")
    else:
        os.rename(
            os.path.join(bets_dir, f"bets_{date_str}.json"),
            os.path.join(bets_dir, f"bets_{date_str}.settled.json"),
        )

    return {"settled": settled, "cumulative": C}


def format_pnl_summary(result: dict | None) -> str:
    """生成结算摘要文本 (复盘报告与命令行复用)"""
    if not result:
        return "今日无投注单，P&L 不结算。"
    settled = result["settled"]
    lines = ["投注结算:", "-" * 40]
    for b in settled:
        name = b.get("note") or f'{b.get("home_team")} vs {b.get("away_team")}'
        lines.append(
            f'  [{b.get("status")}] {name} {b.get("dimension")}/{b.get("direction")} '
            f'@{b.get("odds")} x {b.get("stake")} -> {b.get("payout")} ({b.get("reason")})'
        )
    C = result["cumulative"]
    lines.append(f'累计: {C["n"]}注 投入{C["staked"]} 回收{C["return"]} ROI {C["roi"]:+.1%}')
    return "\n".join(lines)
