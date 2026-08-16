"""
Model Trainer v3.0

Two-pass training pipeline:
1. ELO Calibration: chronologically replay all ~9,000 matches
2. Dixon-Coles Fitting: MLE of attack/defense/rho parameters

Input: list of match dicts from data_loader
Output: persisted ELO ratings + Dixon-Coles parameters
"""
from __future__ import annotations

import json
import os
from typing import Any

from models.elo import EloSystem
from models.dixon_coles import DixonColesModel
from models.league_profiles import LEAGUE_PROFILES, compute_league_profiles_from_matches


def train_all(
    matches: list[dict],
    state_dir: str = "data/state",
    use_mle: bool = True,
) -> dict[str, Any]:
    """Run the full training pipeline.

    Args:
        matches: chronological list of match dicts
        state_dir: directory for persisted state
        use_mle: if True, use scipy MLE; if False, use analytical fit

    Returns:
        Summary dict with training statistics
    """
    os.makedirs(state_dir, exist_ok=True)

    # ================================================================
    # 第1步: ELO校准
    # ================================================================
    print(f"第1步: 从 {len(matches)} 场校准ELO...")

    # 从实际数据计算联赛画像 (覆盖硬编码值)
    data_profiles = compute_league_profiles_from_matches(matches)

    # 合并: 有数据用数据, 无数据回退硬编码
    profiles_for_elo = {}
    for code in set(m["league_code"] for m in matches):
        if code in data_profiles:
            profiles_for_elo[code] = data_profiles[code]
        elif code in LEAGUE_PROFILES:
            profiles_for_elo[code] = LEAGUE_PROFILES[code]

    elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
    elo.initialize_from_matches(matches, profiles_for_elo)
    elo.save()
    print(f"  → {elo.team_count} 支球队获得ELO评分")

    # ================================================================
    # 第2步: Dixon-Coles拟合
    # ================================================================
    print("第2步: 拟合Dixon-Coles参数...")

    dc = DixonColesModel()

    if use_mle:
        dc.fit_mle(matches)
        method = "MLE (scipy BFGS)"
    else:
        dc.fit_simple(matches)
        method = "Analytical (moment-based)"

    dc.save(state_dir)
    print(f"  → {dc.team_count} 支球队获得攻防参数")
    print(f"  → Method: {method}")

    # ================================================================
    # 第3步: 平局校准
    # ================================================================
    print("第3步: 拟合联赛级平局校准...")
    from models.draw_calibration import fit_draw_calibration, save_calibration
    draw_cal = fit_draw_calibration(matches, dc)
    cal_path = os.path.join(state_dir, "draw_calibration.json")
    save_calibration(draw_cal, cal_path)
    boosted = sum(1 for v in draw_cal.values() if v.get("draw_factor", 1.0) > 1.01)
    print(f"  → {len(draw_cal)} 个联赛, {boosted} 个平局加成")

    # ================================================================
    # Summary
    # ================================================================
    summary = {
        "total_matches": len(matches),
        "elo": elo.ratings_summary,
        "dc_teams": dc.team_count,
        "leagues": list(dc.league_rho.keys()),
        "league_params": {
            code: {
                "rho": dc.league_rho.get(code, -0.10),
                "home_adv": dc.league_home_adv.get(code, 0.30),
                "avg_goals": dc.league_avg_goals.get(code, 2.65),
            }
            for code in dc.league_rho
        },
        "fit_method": method,
    }

    # ================================================================
    # Pass 4: 概率校准 (Phase 2 · 拟合于最新赛季之前的数据)
    # ================================================================
    from models.calibration import fit_calibration, save_calibration
    seasons = sorted(set(m["season"] for m in matches))
    cal_matches = [m for m in matches if m["season"] != seasons[-1]] if seasons else matches
    cal_preds = []
    cal_actuals = []
    for m in cal_matches:
        if m["result"] not in ("H", "D", "A"):
            continue
        tp = dc.predict(m["home_team"], m["away_team"], m["league_code"])
        cal_preds.append([tp["home_win"], tp["draw"], tp["away_win"]])
        cal_actuals.append({"H": 0, "D": 1, "A": 2}[m["result"]])
    prob_cal = fit_calibration(cal_preds, cal_actuals)
    save_calibration(prob_cal, os.path.join(state_dir, "calibration.json"))
    print(f"  → 概率校准拟合于 {len(cal_actuals)} 场 (不含最新赛季 {seasons[-1] if seasons else '?'})")

    # Save summary
    summary_path = os.path.join(state_dir, "training_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def train_per_league_models(
    matches: list[dict],
    state_dir: str = "data/state",
) -> dict[str, dict]:
    """分联赛自适应模型 (Phase 9): 每个联赛独立拟合一套 DC 参数 + 平局校准

    保存至 data/state/models/{联赛代码}/, 预测时按比赛联赛选择对应模型。
    """
    from collections import defaultdict
    os.makedirs(os.path.join(state_dir, "models"), exist_ok=True)

    by_league: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        by_league[m["league_code"]].append(m)

    result: dict[str, dict] = {}
    for code, lg_matches in sorted(by_league.items()):
        if len(lg_matches) < 100:
            print(f"  [{code}] 样本不足({len(lg_matches)}), 跳过独立模型")
            continue
        dc = DixonColesModel()
        try:
            dc.fit_mle(lg_matches)
        except Exception:
            dc.fit_simple(lg_matches)
        model_dir = os.path.join(state_dir, "models", code)
        dc.save(model_dir)

        # 联赛独立平局校准
        from models.draw_calibration import fit_draw_calibration, save_calibration
        draw_cal = fit_draw_calibration(lg_matches, dc)
        save_calibration(draw_cal, os.path.join(model_dir, "draw_calibration.json"))

        result[code] = {
            "matches": len(lg_matches),
            "teams": dc.team_count,
            "leagues": list(dc.league_rho.keys()),
        }
        print(f"  [{code}] 独立模型: {len(lg_matches)}场/{dc.team_count}队")

    # 保存清单
    with open(os.path.join(state_dir, "models", "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def load_per_league_models(
    state_dir: str = "data/state",
) -> dict[str, DixonColesModel]:
    """加载全部分联赛模型 → {联赛代码: DixonColesModel}"""
    models: dict[str, DixonColesModel] = {}
    root = os.path.join(state_dir, "models")
    if not os.path.isdir(root):
        return models
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        dc = DixonColesModel()
        if dc.load(d):
            models[name] = dc
    return models


def load_models(
    state_dir: str = "data/state",
) -> tuple[EloSystem, DixonColesModel]:
    """Load previously trained models from disk."""
    elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
    dc = DixonColesModel()

    if not elo.load():
        raise FileNotFoundError(
            f"ELO ratings not found at {state_dir}/elo_ratings.json. Run train first."
        )
    if not dc.load(state_dir):
        raise FileNotFoundError(
            f"Dixon-Coles params not found at {state_dir}. Run train first."
        )

    return elo, dc
