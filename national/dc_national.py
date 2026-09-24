# -*- coding: utf-8 -*-
"""国家队 Dixon-Coles —— 独立实现, 不依赖俱乐部链路。

与 models/dixon_coles.py 的 fit_mle 的三个关键差异:
  1. **支持中立场**: 国家队 1/3 的比赛在中立场, 而俱乐部版没有这个字段。
     中立场时主场优势项直接归零。
  2. **主场优势按赛事类型分组** (友谊/欧国联/预选赛/决赛圈), 而不是"按联赛"。
  3. **友谊赛降权**: 换人多、试验阵容, 比分不代表真实实力。

参数化 (log 线性, 便于岭正则):
    lam_h = exp(mu + att[h] - dfn[a] + ha[comp] * (0 if neutral else 1))
    lam_a = exp(mu + att[a] - dfn[h])
"""
import math, os, sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from national.corpus import FRIENDLY, FRIENDLY_WEIGHT, NL, QUAL, FINALS  # noqa: E402

COMPS = [FRIENDLY, NL, QUAL, FINALS]
COMP_IDX = {c: i for i, c in enumerate(COMPS)}


def poisson_logpmf(k: np.ndarray, lam: np.ndarray) -> np.ndarray:
    from scipy.special import gammaln
    return k * np.log(lam) - lam - gammaln(k + 1.0)


def _tau_and_grad(gh, ga, lam_h, lam_a, rho):
    """返回 (tau, dtau/dlam_h, dtau/dlam_a, dtau/drho) —— 只对 4 个低比分格子非平凡。"""
    one = np.ones_like(lam_h)
    zero = np.zeros_like(lam_h)
    tau = one.copy()
    dh = zero.copy()
    da = zero.copy()
    dr = zero.copy()
    m00 = (gh == 0) & (ga == 0)
    m01 = (gh == 0) & (ga == 1)
    m10 = (gh == 1) & (ga == 0)
    m11 = (gh == 1) & (ga == 1)
    tau[m00] = 1.0 - lam_h[m00] * lam_a[m00] * rho
    dh[m00] = -lam_a[m00] * rho
    da[m00] = -lam_h[m00] * rho
    dr[m00] = -lam_h[m00] * lam_a[m00]
    tau[m01] = 1.0 + lam_h[m01] * rho
    dh[m01] = rho
    dr[m01] = lam_h[m01]
    tau[m10] = 1.0 + lam_a[m10] * rho
    da[m10] = rho
    dr[m10] = lam_a[m10]
    tau[m11] = 1.0 - rho
    dr[m11] = -1.0
    return tau, dh, da, dr


class NationalDC:
    """国家队 Dixon-Coles 模型。"""

    def __init__(self, half_life_days: float = 730.0, alpha_team: float = 0.012,
                 alpha_ha: float = 5.0, alpha_rho: float = 1.0, friendly_weight: float = FRIENDLY_WEIGHT):
        self.half_life_days = float(half_life_days)
        self.alpha_team = float(alpha_team)
        self.alpha_ha = float(alpha_ha)
        self.alpha_rho = float(alpha_rho)
        self.friendly_weight = float(friendly_weight)
        self.teams: list[str] = []
        self.att: dict[str, float] = {}
        self.dfn: dict[str, float] = {}
        self.mu = 0.0
        self.ha: dict[str, float] = {}
        self.rho = -0.10
        self._fitted = False
        self.ref_date = ""

    # ── 训练 ──
    def fit(self, matches: list[dict], verbose: bool = False) -> "NationalDC":
        from scipy.optimize import minimize

        teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
        ti = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        self.teams = teams
        self.ref_date = max(m["date"] for m in matches)

        gh = np.array([m["hg"] for m in matches], dtype=np.float64)
        ga = np.array([m["ag"] for m in matches], dtype=np.float64)
        hi = np.array([ti[m["home"]] for m in matches], dtype=np.int64)
        ai = np.array([ti[m["away"]] for m in matches], dtype=np.int64)
        ci = np.array([COMP_IDX[m["comp"]] for m in matches], dtype=np.int64)
        neutral = np.array([bool(m["neutral"]) for m in matches], dtype=np.float64)
        # 权重 = 时间衰减 × 赛事权重, 再归一化到均值 1 (与俱乐部版同样的纪律:
        # 不归一化的话, 衰减强度会和正则强度纠缠, 网格搜索出来的参数无法解释)
        rdt = np.array([_days(m["date"], self.ref_date) for m in matches], dtype=np.float64)
        w_time = np.power(0.5, rdt / self.half_life_days)
        w_comp = np.where(np.array([m["comp"] for m in matches]) == FRIENDLY,
                          self.friendly_weight, 1.0)
        w = w_time * w_comp
        w = w / w.mean()
        self._w = w

        x0 = np.zeros(2 * n + len(COMPS) + 2)
        x0[2 * n] = math.log(2.65)          # mu: 国际比赛场均总进球 ~2.6-2.7
        x0[2 * n + 1: 2 * n + 1 + len(COMPS)] = 0.25   # 主场优势初值
        x0[-1] = -0.10                       # rho

        bounds = ([(-3.0, 3.0)] * (2 * n)
                  + [(0.0, 1.5)]
                  + [(0.0, 0.8)] * len(COMPS)
                  + [(-0.45, 0.45)])

        def unpack(x):
            return x[:n], x[n:2 * n], x[2 * n], x[2 * n + 1: 2 * n + 1 + len(COMPS)], x[-1]

        def fg(x):
            at, df, mu, ha, rho = unpack(x)
            xh = mu + at[hi] - df[ai] + ha[ci] * (1.0 - neutral)
            xa = mu + at[ai] - df[hi]
            lam_h = np.exp(np.clip(xh, -6, 6))
            lam_a = np.exp(np.clip(xa, -6, 6))
            tau, dth, dta, dtr = _tau_and_grad(gh, ga, lam_h, lam_a, rho)
            tau = np.maximum(tau, 1e-9)
            ll = (np.log(tau) + poisson_logpmf(gh, lam_h) + poisson_logpmf(ga, lam_a))
            obj = -np.sum(w * ll)
            obj += self.alpha_team * (np.sum(at ** 2) + np.sum(df ** 2))
            obj += self.alpha_ha * np.sum(ha ** 2)
            obj += self.alpha_rho * rho ** 2
            if not np.isfinite(obj):
                obj = 1e12
            # ── 解析梯度 ──
            inv_tau = 1.0 / tau
            dl_dlh = inv_tau * dth + gh / lam_h - 1.0
            dl_dla = inv_tau * dta + ga / lam_a - 1.0
            dl_dx_h = lam_h * dl_dlh      # 链式: d/dx = lam * d/dlam
            dl_dx_a = lam_a * dl_dla
            g_h = -(w * dl_dx_h)
            g_a = -(w * dl_dx_a)
            g = np.zeros_like(x)
            g[:n] = np.bincount(hi, weights=g_h, minlength=n) + np.bincount(ai, weights=g_a, minlength=n)
            # 注意负号: x_h 里 dfn[away] 是 -1 系数, x_a 里 dfn[home] 也是 -1。
            # 2026-09-24 曾漏掉这个负号 -> 优化器一步冲到边界, 四场预测完全相同。
            g[n:2 * n] = -(np.bincount(ai, weights=g_h, minlength=n)
                           + np.bincount(hi, weights=g_a, minlength=n))
            g[2 * n] = np.sum(g_h + g_a)
            g[2 * n + 1: 2 * n + 1 + len(COMPS)] = np.bincount(
                ci, weights=g_h * (1.0 - neutral), minlength=len(COMPS))
            g[-1] = -np.sum(w * inv_tau * dtr)
            g[:2 * n] += 2.0 * self.alpha_team * np.concatenate([at, df])
            g[2 * n + 1: 2 * n + 1 + len(COMPS)] += 2.0 * self.alpha_ha * ha
            g[-1] += 2.0 * self.alpha_rho * rho
            return obj, g

        res = minimize(fg, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 800, "ftol": 1e-10, "gtol": 1e-7})
        at, df, mu, ha, rho = unpack(res.x)
        self.att = {t: float(at[i]) for i, t in enumerate(teams)}
        self.dfn = {t: float(df[i]) for i, t in enumerate(teams)}
        self.mu = float(mu)
        self.ha = {c: float(ha[i]) for i, c in enumerate(COMPS)}
        self.rho = float(rho)
        # 平移不变性: att 和 dfn 同时加同一个常数, 所有 lam 不变。这里把两者都中心化到均值 0,
        # 只为了让 mu 可以解释成"平均球队对平均球队的场均进球", 不影响任何预测。
        ca = float(np.mean(at))
        cd = float(np.mean(df))
        for i, t in enumerate(teams):
            self.att[t] = float(at[i] - ca)
            self.dfn[t] = float(df[i] - cd)
        self._fitted = True
        self.fit_info = {"success": bool(res.success), "nit": int(res.nit),
                         "n_matches": len(matches), "n_teams": n,
                         "neg_ll": float(res.fun)}
        if verbose:
            print("  拟合: %s  nit=%d  场次=%d  球队=%d  NLL=%.1f"
                  % ("OK" if res.success else "未收敛", res.nit, len(matches), n, res.fun))
            print("  mu(场均总进球)=%.3f  rho=%.3f" % (math.exp(mu) * 2, rho))
            for c in COMPS:
                print("    主场优势[%-8s] = x%.3f  (%.0f Elo 分)" % (c, math.exp(self.ha[c]), self.ha[c] * 400 / math.log(10)))
        return self

    # ── 预测 ──
    def lambdas(self, home: str, away: str, neutral: bool = False, comp: str = NL):
        if home not in self.att or away not in self.att:
            missing = [t for t in (home, away) if t not in self.att]
            raise KeyError("模型里没有这支球队: %s" % missing)
        ha = 0.0 if neutral else self.ha.get(comp, self.ha.get(QUAL, 0.25))
        lh = math.exp(self.mu + self.att[home] - self.dfn[away] + ha)
        la = math.exp(self.mu + self.att[away] - self.dfn[home])
        return lh, la

    def predict(self, home: str, away: str, neutral: bool = False, comp: str = NL, max_g: int = 10) -> dict:
        """返回 1X2 / 大小球 / 波胆 概率。用 dc_marginals 以外的本地实现, 保证 max_g 可控。"""
        lh, la = self.lambdas(home, away, neutral, comp)
        p = np.zeros((max_g + 1, max_g + 1))
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                t = 1.0
                if i == 0 and j == 0:
                    t = 1.0 - lh * la * self.rho
                elif i == 0 and j == 1:
                    t = 1.0 + lh * self.rho
                elif i == 1 and j == 0:
                    t = 1.0 + la * self.rho
                elif i == 1 and j == 1:
                    t = 1.0 - self.rho
                p[i, j] = max(t, 1e-12) * _pois(i, lh) * _pois(j, la)
        p = p / p.sum()
        hw = float(np.tril(p, -1).sum())
        dr = float(np.trace(p))
        aw = float(np.triu(p, 1).sum())
        tot = np.add.outer(np.arange(max_g + 1), np.arange(max_g + 1))
        over25 = float(p[tot > 2.5].sum())
        over15 = float(p[tot > 1.5].sum())
        over35 = float(p[tot > 3.5].sum())
        btts = float(p[1:, 1:].sum())
        idx = np.dstack(np.unravel_index(np.argsort(-p, axis=None), p.shape))[0][:5]
        return {
            "home_win": round(hw, 4), "draw": round(dr, 4), "away_win": round(aw, 4),
            "over_15": round(over15, 4), "over_25": round(over25, 4), "over_35": round(over35, 4),
            "btts": round(btts, 4),
            "lam_h": round(lh, 3), "lam_a": round(la, 3),
            "top_scores": [("%d-%d" % (int(i), int(j)), round(float(p[i, j]), 4)) for i, j in idx],
            "neutral": neutral, "comp": comp,
        }

    def ratings(self) -> list[tuple]:
        """净强度 = att + dfn (越大越强), 用于人肉核对常识。"""
        rows = [(t, self.att[t], self.dfn[t], self.att[t] + self.dfn[t]) for t in self.teams]
        rows.sort(key=lambda r: -r[3])
        return rows


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.gamma(k + 1)


def _days(d1: str, d2: str) -> int:
    from datetime import date as _d
    a = _d(*[int(x) for x in d1.split("-")])
    b = _d(*[int(x) for x in d2.split("-")])
    return (b - a).days