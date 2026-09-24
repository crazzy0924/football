# -*- coding: utf-8 -*-
"""国家队 Elo —— 按 World Football Elo Ratings 的口径, 独立实现。

要点:
  - K 值按赛事重要度: 友谊 20 / 欧国联·预选赛 40 / 决赛圈 50
  - 净胜球乘子 G: GD<=1 -> 1.0, GD=2 -> 1.5, GD>=3 -> (11+GD)/8
  - 主场加分 +100 Elo, 中立场不加
  - 初始 1500
"""
from national.corpus import FRIENDLY, FINALS, NL, QUAL

HOME_BONUS = 100.0
INITIAL = 1500.0

K_BY_COMP = {FRIENDLY: 20.0, NL: 40.0, QUAL: 40.0, FINALS: 50.0}


def _g(gd: int) -> float:
    gd = abs(int(gd))
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


def _we(dr: float) -> float:
    return 1.0 / (10.0 ** (-dr / 400.0) + 1.0)


def compute_elo(matches: list[dict], home_bonus: float = HOME_BONUS):
    """按时间顺序滚一遍。返回 (rating_dict, pre_diffs)。

    pre_diffs[i] = 该场赛前的 (主队 Elo + 主场加分) - 客队 Elo —— 只用了赛前信息。
    """
    r: dict[str, float] = {}
    pre = []
    for m in matches:
        h, a = m["home"], m["away"]
        rh = r.get(h, INITIAL)
        ra = r.get(a, INITIAL)
        bonus = 0.0 if m["neutral"] else home_bonus
        pre.append((rh + bonus) - ra)
        we = _we((rh + bonus) - ra)
        w = 1.0 if m["hg"] > m["ag"] else (0.5 if m["hg"] == m["ag"] else 0.0)
        k = K_BY_COMP.get(m["comp"], 40.0)
        delta = k * _g(m["hg"] - m["ag"]) * (w - we)
        r[h] = rh + delta
        r[a] = ra - delta
    return r, pre


def fit_outcome_table(matches: list[dict], pre: list[float], bin_width: float = 50.0,
                      lo: float = -700.0, hi: float = 700.0) -> dict:
    """把 Elo 差分桶, 统计经验 H/D/A 频率。这是 Elo -> 1X2 的非参数映射。

    只在训练集上拟合, 避免泄漏。桶内样本过少时向全局基准收缩。
    """
    nb = int((hi - lo) / bin_width) + 1
    cnt = [[0, 0, 0] for _ in range(nb)]
    base = [0, 0, 0]
    for m, d in zip(matches, pre):
        b = int((d - lo) / bin_width)
        b = 0 if b < 0 else (nb - 1 if b >= nb else b)
        k = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
        cnt[b][k] += 1
        base[k] += 1
    tot = sum(base)
    base = [c / tot for c in base]
    PRIOR = 30.0   # 收缩强度: 桶内不足 30 场就大量借全局
    table = []
    for c in cnt:
        n = sum(c)
        table.append([(c[i] + PRIOR * base[i]) / (n + PRIOR) for i in range(3)])
    return {"lo": lo, "bin_width": bin_width, "nb": nb, "table": table, "base": base}


def lookup(table: dict, diff: float) -> list[float]:
    b = int((diff - table["lo"]) / table["bin_width"])
    b = 0 if b < 0 else (table["nb"] - 1 if b >= table["nb"] else b)
    return table["table"][b]