# -*- coding: utf-8 -*-
"""把 xG 融进 Dixon-Coles 的拟合目标 —— **实验开关, 默认关闭**。

证据 (docs/xG接入评估计划.md 第七、八节):
  纯模型下 xG 显著有效 (w=0.5 时 -0.00160, t=-3.94, 三个完整赛季各自独立显著);
  但生产链路(市场融合后)增益缩到 -0.00070 (t=-2.72), **四个赛季无一单独显著**,
  只填平与市场差距(0.0111)的 6.3%。且只有 BL1 通过多重比较校正。
所以默认关闭, 只作实验用。

开关 (环境变量):
  FOOTBALL_XG_WEIGHT   融合权重 w   0=关闭(默认), 0.5=实验推荐值
  FOOTBALL_XG_LEAGUES  只对这些联赛生效 (逗号分隔, 留空=全部)

注意: 融合只作用于**拟合目标**。平局校准等按下游必须仍用**原始赛果**,
否则会拿被 xG 改过的比分去校准真实结果 —— 那是错的。
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.team_names import canonical_of as C  # noqa: E402

_INDEX = None


def _key(name: str) -> str:
    return C(name) or (name or "").strip().lower()


def load_index() -> dict:
    """(赛季, 主队键, 客队键) → (xg_h, xg_a)"""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    idx: dict = {}
    for f in glob.glob(os.path.join("data", "state", "xg", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        s = d.get("season")
        for v in (d.get("matches") or {}).values():
            if v.get("xg_h") is None or v.get("xg_a") is None:
                continue
            h, a = _key(v.get("home") or ""), _key(v.get("away") or "")
            if h and a:
                idx[(s, h, a)] = (float(v["xg_h"]), float(v["xg_a"]))
    _INDEX = idx
    return idx


def enabled_weight() -> float:
    try:
        return float(os.environ.get("FOOTBALL_XG_WEIGHT") or 0)
    except ValueError:
        return 0.0


def maybe_blend(matches: list, league_code: str) -> tuple[list, dict | None]:
    """按环境变量决定是否融合。返回 (用于拟合的比赛列表, 统计信息或 None)。

    未启用或该联赛不在范围内时, 原样返回同一个列表 (零开销)。
    """
    w = enabled_weight()
    if w <= 0:
        return matches, None
    only = {x.strip().upper() for x in
            (os.environ.get("FOOTBALL_XG_LEAGUES") or "").split(",") if x.strip()}
    if only and (league_code or "").upper() not in only:
        return matches, None

    idx = load_index()
    out, n = [], 0
    for m in matches:
        g = idx.get((m.get("season"), _key(m.get("home_team") or ""),
                     _key(m.get("away_team") or "")))
        if g:
            mm = dict(m)
            mm["home_goals"] = w * g[0] + (1.0 - w) * m["home_goals"]
            mm["away_goals"] = w * g[1] + (1.0 - w) * m["away_goals"]
            out.append(mm)
            n += 1
        else:
            out.append(m)
    return out, {"w": w, "blended": n, "total": len(matches)}
