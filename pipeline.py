#!/usr/bin/env python
"""
Football Prediction Pipeline v3.0 — Single Entry Point

Usage:
  python pipeline.py train              # Fit ELO + Dixon-Coles from 25 CSVs
  python pipeline.py backtest           # Time-series CV, must beat baseline
  python pipeline.py predict            # Predict today's matches (needs odds API)
  python pipeline.py review YYYY-MM-DD  # Evaluate predictions vs results
  python pipeline.py full               # train → backtest → (predict if passed)
  python pipeline.py summary            # Show model state summary

Design principles:
  1. Data-first: all model parameters learned from historical CSVs
  2. One model: Dixon-Coles, not five disconnected bases
  3. Gated deployment: backtesting must pass before live prediction
  4. Single responsibility: each command does one thing well
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

# ---- Windows GBK修复: 强制UTF-8输出 ----
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def cmd_train(args):
    """Train ELO and Dixon-Coles from historical CSV + openfootball data."""
    from pipeline.data_loader import load_all_matches
    from pipeline.trainer import train_all

    csv_dir = args.csv_dir or "data/historical_odds"
    state_dir = args.state_dir or "data/state"

    print("加载全部比赛数据...")
    matches = load_all_matches(csv_dir)
    # 聚焦联赛过滤 (2026-08-16: 只训练五大联赛, 聚焦回测Brier 0.595 vs 全量0.626)
    from config import FOCUS_LEAGUES
    matches = [m for m in matches if m["league_code"] in FOCUS_LEAGUES]
    print(f"聚焦后 {len(matches)} 场比赛 ({FOCUS_LEAGUES}), 来自 {len(set(m['season'] for m in matches))} 个赛季")

    summary = train_all(matches, state_dir, use_mle=args.mle)

    # Phase 9: 分联赛自适应模型 (每联赛独立DC+平局校准, 预测时按联赛选择)
    from pipeline.trainer import train_per_league_models
    per_league = train_per_league_models(matches, state_dir)

    print("\n[OK] 训练完成")
    print(f"  ELO球队数: {summary['elo']['teams']}")
    print(f"  攻防参数球队数: {summary['dc_teams']}")
    print(f"  训练联赛: {summary['leagues']}")
    print(f"  拟合方法: {summary['fit_method']}")
    print(f"  分联赛模型: {list(per_league.keys())}")
    print(f"  状态已保存至 {state_dir}/")
def cmd_backtest(args):
    """Run time-series cross-validation backtest."""
    from pipeline.data_loader import load_all_matches
    from pipeline.backtester import run_backtest

    csv_dir = args.csv_dir or "data/historical_odds"
    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"

    print("加载全部比赛数据...")
    matches = load_all_matches(csv_dir)
    # 聚焦联赛过滤 (与训练同口径)
    from config import FOCUS_LEAGUES
    matches = [m for m in matches if m["league_code"] in FOCUS_LEAGUES]
    print(f"聚焦后 {len(matches)} 场比赛 ({FOCUS_LEAGUES})")

    report = run_backtest(matches, state_dir, output_dir, recent_seasons=args.recent_seasons)

    if report.get("gate_result") == "FAIL":
        print("\n⚠ 回测门禁未通过 — 模型禁止上线")
        if not args.force:
            sys.exit(1)
    else:
        print("\n[PASS] 回测门禁通过 — 模型可上线")


def cmd_predict(args):
    """Generate predictions for today's matches."""
    from pipeline.trainer import load_models
    from models.dixon_coles import dc_marginals

    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"
    csv_dir = args.csv_dir or "data/historical_odds"

    # 加载训练好的模型
    try:
        elo, dc = load_models(state_dir)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"已加载: {elo.team_count} 支ELO球队, {dc.team_count} 组DC参数")

    # 加载平局校准 (统一模型, 兜底)
    from models.draw_calibration import load_calibration, apply_draw_calibration
    draw_cal = load_calibration(os.path.join(state_dir, "draw_calibration.json"))
    if draw_cal:
        n_cal = len(draw_cal)
        boosted = sum(1 for v in draw_cal.values() if v.get("draw_factor", 1.0) > 1.01)
        print(f"平局校准: {n_cal} 个联赛, {boosted} 个平局加成")
    else:
        print("平局校准: 不可用(先跑backtest生成)")

    # Phase 9: 分联赛自适应模型 (每联赛独立DC+独立平局校准, 按比赛联赛选择)
    from pipeline.trainer import load_per_league_models
    league_models = load_per_league_models(state_dir)
    league_draw_cals: dict = {}
    for lg, lg_dc in league_models.items():
        c = load_calibration(os.path.join(state_dir, "models", lg, "draw_calibration.json"))
        if c:
            league_draw_cals[lg] = c
    if league_models:
        print(f"分联赛模型: {list(league_models.keys())} (预测时按联赛选择, 兜底统一模型)")

    # 近期状态因子 (与回测同口径, Phase 7.5: 回测Brier 0.595依赖此步)
    form_factors = {}
    try:
        from pipeline.data_loader import load_all_matches
        from config import FOCUS_LEAGUES
        from models.form_factor import compute_form_factors
        hist = [m for m in load_all_matches(csv_dir or "data/historical_odds") if m["league_code"] in FOCUS_LEAGUES]
        form_factors = compute_form_factors(
            hist, dc.team_attack, dc.team_defense,
            dc.league_avg_goals, dc.league_home_adv,
        )
        n_form = sum(1 for v in form_factors.values() if v.get("n_matches", 0) >= 3)
        print(f"状态因子: {n_form} 支球队已计算")
    except Exception as e:
        print(f"状态因子计算失败(回退无因子): {e}")

    # 加载积分榜 (Phase 7, football-data.org 免费档)
    standings = {}
    try:
        sp = os.path.join(state_dir, "standings.json")
        if os.path.exists(sp):
            with open(sp, "r", encoding="utf-8") as f:
                standings = json.load(f)
            print(f"积分榜: {sum(len(t) for t in standings.values())} 队已加载")
    except Exception as e:
        print(f"积分榜加载失败: {e}")

    # 概率校准 (Phase 2): 回测实测无增益 (两折均 +0.002), 实盘默认不启用
    prob_cal = None

    # 尝试拉取实时赔率
    api_matches = None
    try:
        from pipeline.odds_fetcher import fetch_today_matches
        api_matches = fetch_today_matches()
        print(f"从赔率API拉取 {len(api_matches)} 场比赛")
    except Exception as e:
        print(f"赔率API不可用: {e}")

    # 从JSON加载比赛列表(含中文队名的权威名单)
    if args.matches_json:
        with open(args.matches_json, "r", encoding="utf-8") as f:
            matches = json.load(f)
        print(f"从 {args.matches_json} 加载 {len(matches)} 场比赛")
    elif api_matches:
        matches = api_matches
    else:
        print("无比赛可预测。请提供 --matches-json 或确认赔率API可用。")
        sys.exit(1)

    # API赔率合并进JSON比赛(队名模糊匹配)
    if api_matches and args.matches_json:
        def _clean(s):
            import unicodedata
            s = s.lower().replace(' ','').replace('-','').replace('.','')
            return ''.join(c for c in unicodedata.normalize('NFKD', s) if ord(c) < 128)
        api_lookup = {}
        for am in api_matches:
            key = (_clean(am['home_team']), _clean(am['away_team']))
            api_lookup[key] = am.get('odds')
        merged = 0
        for m in matches:
            if m.get('odds'):
                continue  # already has odds
            h = m.get('home_team',''); a = m.get('away_team','')
            k = (_clean(h), _clean(a))
            if k in api_lookup:
                m['odds'] = api_lookup[k]
                merged += 1
        if merged > 0:
            print(f"合并赔率: {merged}/{len(matches)} 场")

    if not matches:
        print("无比赛可预测。")
        return

    # Phase 8: 赛程密度 + 近2季交锋 预计算 (h2h 全库)
    sched_cache: dict = {}
    h2h_cache: dict = {}

    def _team_recent(name: str, days: int = 7, db=None) -> int:
        if name in sched_cache:
            return sched_cache[name]
        if not db:
            sched_cache[name] = 0
            return 0
        cutoff = datetime.now() - timedelta(days=days)
        n = 0
        for mm in db.get("matches", []):
            if mm.get("home_team") == name or mm.get("away_team") == name:
                try:
                    if datetime.strptime(str(mm.get("date", "")), "%Y-%m-%d") >= cutoff:
                        n += 1
                except Exception:
                    pass
        sched_cache[name] = n
        return n

    def _recent_h2h(home: str, away: str, db=None) -> dict | None:
        key = f"{home}|{away}"
        if key in h2h_cache:
            return h2h_cache[key]
        if not db:
            h2h_cache[key] = None
            return None
        seasons = sorted({str(mm.get("season", "")) for mm in db.get("matches", [])})
        recent_seasons = set(seasons[-2:])  # 只看近2个赛季
        w = d = l = 0
        gf = ga = 0
        for mm in db.get("matches", []):
            if str(mm.get("season", "")) not in recent_seasons:
                continue
            h = mm.get("home_team")
            a = mm.get("away_team")
            if (h == home and a == away) or (h == away and a == home):
                gh = mm.get("home_goals")
                ga2 = mm.get("away_goals")
                if gh is None or ga2 is None:
                    continue
                if h == home:
                    hf, af = gh, ga2
                else:
                    hf, af = ga2, gh
                gf += hf
                ga += af
                if hf > af:
                    w += 1
                elif hf == af:
                    d += 1
                else:
                    l += 1
        if w + d + l == 0:
            h2h_cache[key] = None
            return None
        h2h_cache[key] = {"w": w, "d": d, "l": l, "gf": gf, "ga": ga}
        return h2h_cache[key]

    _db = None
    try:
        if os.path.exists("data/local_match_db.json"):
            with open("data/local_match_db.json", "r", encoding="utf-8") as f:
                _db = json.load(f)
    except Exception:
        _db = None

    from datetime import datetime, timedelta

    # 逐场预测
    predictions = []
    for m in matches:
        home = m.get("home_team") or m.get("home")
        away = m.get("away_team") or m.get("away")
        league = m.get("league_code") or m.get("league", "PL")

        if not home or not away:
            continue

        # 队名标准化为CSV规范形式
        from pipeline.data_loader import normalize_team_name
        home = normalize_team_name(home)
        away = normalize_team_name(away)

        # ── 市场驱动冷启动: 把市场赔率传给DC ──
        market = m.get("odds") or m.get("market_odds")
        # Phase 9: 按联赛选择独立模型 (缺则回退统一模型)
        dc_use = league_models.get(league, dc)
        pred = dc_use.predict(home, away, league, form_factors=form_factors, market_odds=market)

        # 应用平局校准 (联赛独立校准优先, 统一校准兜底)
        draw_cal_use = league_draw_cals.get(league, draw_cal)
        cal_h, cal_d, cal_a = apply_draw_calibration(
            {"home_win": pred["home_win"], "draw": pred["draw"], "away_win": pred["away_win"]},
            league, draw_cal_use,
        )
        pred["home_win"] = cal_h
        pred["draw"] = cal_d
        pred["away_win"] = cal_a

        # 实验位: 概率校准(PAV) — 实测无增益, 保持关闭
        # if prob_cal:  # 实验开关
        #     pc_h, pc_d, pc_a = apply_prob_cal(...)  # 校准调用占位
        #     pred["home_win"], pred["draw"], pred["away_win"] = pc_h, pc_d, pc_a  # 占位

        elo_h = elo.get_elo(home, league)
        elo_a = elo.get_elo(away, league)

        # 市场对比
        if market:
            from models.odds import detect_value, implied_probability
            from models.bayesian import bayesian_fusion_predict

            value = detect_value(
                [pred["home_win"], pred["draw"], pred["away_win"]],
                market,
            )
            # ── 冷启动: 降低模型置信度让贝叶斯倾向市场 ──
            is_cold = pred.get("cold_start", False)
            mc = 0.20 if is_cold else 0.50  # cold: 20% model, 80% market
            bayes = bayesian_fusion_predict(
                [pred["home_win"], pred["draw"], pred["away_win"]],
                market,
                model_confidence=mc,
            )
        else:
            value = None
            bayes = None

        # 让球盘预测(如有AH赔率)
        ah_pred = None
        ah_line = m.get("ah_line") or m.get("goal_line") or m.get("handicap")
        ah_odds = m.get("ah_odds")
        if ah_line is not None and ah_odds:
            from pipeline.five_dim_predictor import compute_handicap_probs, analyze_hhad_edge
            ah_probs = compute_handicap_probs(pred["score_distribution"], ah_line)
            ah_edge = analyze_hhad_edge(ah_probs, ah_odds)
            ah_pred = {
                "goal_line": ah_line,
                "home_cover": ah_probs["home_cover"],
                "push": ah_probs["push"],
                "away_cover": ah_probs["away_cover"],
                "edge": ah_edge,
            }

        predictions.append({
            "home_team": home,
            "away_team": away,
            "league_code": league,
            "odds": market,
            "elo_home": elo_h,
            "elo_away": elo_a,
            "elo_diff": round(elo_h - elo_a, 1),
            "model": pred,
            "value": {
                "home_edge": value.home_value,
                "draw_edge": value.draw_value,
                "away_edge": value.away_value,
                "best_direction": value.best_direction,
                "kelly": value.kelly_fraction,
                "confidence": value.confidence,
            } if value else None,
            "bayesian": bayes,
            "cold_start": pred.get("cold_start", False),
            # Phase 1 A2: 无赔率且冷启动 → 预测退化为联赛先验，无信息量
            "no_signal": value is None and pred.get("cold_start", False),
            "ah_handicap": ah_pred,
            # Phase 10: 波胆价值 + 大小球价值 (模型 vs 市场多维度 edge)
            "cs_value": _cs_value(pred, m),
            "ou_value": _ou_value(pred, m),
            "ht_ft_odds": m.get("ht_ft_odds") or {},
            # Phase 7: 积分榜快照 (排名/积分/近况)
            "standings": {
                "home": _standings_lookup(standings.get(league), home),
                "away": _standings_lookup(standings.get(league), away),
            },
            # Phase 8: 赛程密度 (7天内) + 近2季交锋
            "schedule": {
                "home_7d": _team_recent(home, 7, _db),
                "away_7d": _team_recent(away, 7, _db),
            },
            "h2h_recent": _recent_h2h(home, away, _db),
        })

    # 保存JSON
    os.makedirs(output_dir, exist_ok=True)
    today_str = _today_str()
    out_path = os.path.join(output_dir, f"predictions_{today_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(predictions)} 条预测至 {out_path}")

    # 生成HTML (早盘/午盘=七维分析存档页, 终盘=预测页)
    stage = getattr(args, "stage", "final")
    try:
        from pipeline.reporter import generate_report

        # 可选LLM定性分析
        analyst_notes = None
        intel_text = ""
        if args.llm:
            print(f"\n[LLM] 正在对 {len(predictions)} 场比赛运行定性分析...")
            # 赛前情报注入 (data/intel/YYYY-MM-DD.txt, 用户手写伤停/首发/战意)
            intel_path = os.path.join("data", "intel", f"{today_str}.txt")
            if os.path.exists(intel_path):
                with open(intel_path, "r", encoding="utf-8") as f:
                    intel_text = f.read().strip()
                if intel_text:
                    print(f"[LLM] 已注入赛前情报 ({intel_path}, {len(intel_text)} 字)")
            # 终盘: 注入早盘/午盘七维分析存档 (可追溯, 防终盘出错)
            prior_notes: dict = {}
            if stage == "final":
                for st in ("morning", "midday"):
                    prior_path = os.path.join(output_dir, f"analysis_notes_{st}_{today_str}.json")
                    if os.path.exists(prior_path):
                        try:
                            with open(prior_path, "r", encoding="utf-8") as f:
                                prior_notes.update(json.load(f))
                        except Exception:
                            pass
                if prior_notes:
                    print(f"[LLM] 已注入早盘/午盘分析存档 {len(prior_notes)} 场")
            try:
                from pipeline.analyst import batch_analyze
                analyst_notes = batch_analyze(predictions, intel_text=intel_text, prior_notes=prior_notes)
                n_notes = sum(1 for v in analyst_notes.values() if v and not v.startswith("["))
                print(f"[LLM] 已标注 {n_notes}/{len(predictions)} 场")
                # 存档本次分析笔记 (供后续阶段注入/重渲染)
                notes_path = os.path.join(output_dir, f"analysis_notes_{stage}_{today_str}.json")
                with open(notes_path, "w", encoding="utf-8") as f:
                    json.dump(analyst_notes or {}, f, ensure_ascii=False, indent=2)
                print(f"[LLM] 分析笔记已存档 → {notes_path}")
            except Exception as e:
                print(f"[LLM] 分析失败: {e}")

        if stage in ("morning", "midday"):
            # 早盘/午盘: 只出七维分析存档页, 不出预测
            from pipeline.analysis_page import generate_analysis_page
            html_path = generate_analysis_page(today_str, stage, predictions, analyst_notes, intel_text)
        else:
            html_path = generate_report(predictions, output_dir, analyst_notes=analyst_notes)
        print(f"HTML报告: {html_path}")
    except Exception as e:
        print(f"HTML报告生成失败: {e}")

    # 打印汇总表
    print(f"\n{'主队':<20} {'客队':<20} {'主':>6} {'平':>6} {'客':>6} {'方向':>10} {'Edge':>6}")
    print("-" * 80)
    for p in predictions:
        m = p["model"]
        pick = "Home" if m["home_win"] >= m["away_win"] and m["home_win"] >= m["draw"] else \
               "Away" if m["away_win"] >= m["home_win"] and m["away_win"] >= m["draw"] else "Draw"
        edge_str = p["value"]["best_direction"] if p["value"] else "-"
        print(f"{p['home_team']:<20} {p['away_team']:<20} "
              f"{m['home_win']:>6.1%} {m['draw']:>6.1%} {m['away_win']:>6.1%} "
              f"{pick:>10} {edge_str:>6}")


def cmd_review(args):
    """Evaluate predictions against actual results.

    Results can be provided via:
      --results-json path/to/results.json
      --results-text "TeamA 2-1 TeamB\\nTeamC 0-0 TeamD"
      Auto-fetch from odds-api.io (if API key configured)

    Generates:
      - Review HTML report (data/output/review_YYYY-MM-DD.html)
      - Updated daily_tracking.json
      - Updated ELO ratings
    """
    date_str = args.date
    state_dir = args.state_dir or "data/state"
    output_dir = args.output_dir or "data/output"

    # Load predictions
    pred_path = os.path.join(output_dir, f"predictions_{date_str}.json")
    if not os.path.exists(pred_path):
        print(f"未找到 {date_str} 的预测: {pred_path}")
        sys.exit(1)

    with open(pred_path, "r", encoding="utf-8") as f:
        predictions = json.load(f)
    print(f"加载 {len(predictions)} 条预测，来自 {pred_path}")

    # ---- 加载赛果 ----
    from pipeline.result_fetcher import (
        load_results_from_json,
        load_results_from_text,
        try_fetch_results,
        match_predictions_to_results,
    )

    results = None

    # 1) Try --results-text
    if args.results_text:
        results = load_results_from_text(args.results_text)
        print(f"从 --results-text 解析 {len(results)} 条赛果")

    # 2) Try --results-json
    if not results and args.results_json:
        if os.path.exists(args.results_json):
            results = load_results_from_json(args.results_json)
            print(f"加载 {len(results)} 条赛果，来自 {args.results_json}")

    # 3) Try auto-fetch
    if not results:
        results = try_fetch_results(date_str)
        if results:
            print(f"从API拉取 {len(results)} 条赛果")

    # 3.5) API-Football 赛果 (Phase 6, 覆盖最全)
    if not results:
        from pipeline.result_fetcher import try_fetch_results_apifootball
        results = try_fetch_results_apifootball(date_str)
        if results:
            print(f"从API-Football拉取 {len(results)} 条赛果")

    # 3.6) football-data.org 赛果 (Phase 6b, 注册即用)
    if not results:
        from pipeline.result_fetcher import try_fetch_results_footballdata
        results = try_fetch_results_footballdata(date_str)
        if results:
            print(f"从football-data.org拉取 {len(results)} 条赛果")

    # 4) 兜底: 查找默认赛果文件
    default_results = os.path.join(output_dir, f"results_{date_str}.json")
    if not results:
        if os.path.exists(default_results):
            results = load_results_from_json(default_results)
            print(f"加载 {len(results)} 条赛果，来自 {default_results}")

    # 4.5) 自动拉取的赛果落盘 (供 h2h 回灌与后续复用)
    if results and not os.path.exists(default_results):
        try:
            with open(default_results, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"[赛果] 已落盘 {len(results)} 条 → {default_results}")
        except Exception as e:
            print(f"[赛果] 落盘失败: {e}")

    if not results:
        print(f"\n未找到 {date_str} 的赛果。")
        print("请通过以下方式提供赛果：")
        print(f"  1. --results-json PATH   (JSON 文件)")
        print(f"  2. --results-text TEXT   (例: 'Arsenal 2-1 Liverpool')")
        print(f"  3. 创建 {output_dir}/results_{date_str}.json")
        print(f"\n格式: [{{\"home_team\":\"A\",\"away_team\":\"B\",\"home_goals\":2,\"away_goals\":1}}]")
        sys.exit(1)

    # ---- 预测与赛果匹配 ----
    matched = match_predictions_to_results(predictions, results)
    print(f"匹配 {len(matched)}/{len(predictions)} 条预测与赛果")

    if not matched:
        print("未找到匹配的赛果，请检查球队名。")
        sys.exit(1)

    # ---- 增量复盘状态: 赛果分波到达时只处理新增场次 ----
    def _mkey(m):
        return f"{m['home_team']}|{m['away_team']}"

    review_state_path = os.path.join(state_dir, "reviewed_dates.json")
    if os.path.exists(review_state_path):
        try:
            with open(review_state_path, "r", encoding="utf-8") as f:
                review_state = json.load(f)
        except Exception:
            review_state = {}
    else:
        review_state = {}
    if isinstance(review_state, list):  # 旧格式迁移: 日期列表=各日已全部处理
        review_state = {"dates": {d: None for d in review_state}}
    if not isinstance(review_state.get("dates"), dict):
        review_state["dates"] = {}

    done = review_state["dates"].get(date_str, [])
    if done is None:
        new_matched = []
    else:
        done_set = set(done)
        new_matched = [m for m in matched if _mkey(m) not in done_set]
    print(f"本次新增 {len(new_matched)}/{len(matched)} 场 (该日已处理 {len(matched) - len(new_matched)} 场)")

    # ---- 更新ELO (只处理新增场次) ----
    elo = None
    elo_changes = []
    try:
        from models.elo import EloSystem
        elo = EloSystem(state_path=os.path.join(state_dir, "elo_ratings.json"))
        elo.load()
    except Exception as e:
        print(f"ELO load failed: {e}")

    if elo and new_matched:
        from pipeline.reporter import TEAM_CN
        for m in new_matched:
                home = m["home_team"]
                away = m["away_team"]
                gh = m.get("home_goals")
                ga = m.get("away_goals")
                league = m.get("league_code", "")
                if not home or not away or gh is None or ga is None:
                    continue

                ha = elo._league_home_advantage.get(league, 100)
                old_h = elo.get_elo(home, league)
                old_a = elo.get_elo(away, league)

                # 冷启动球队跳过ELO更新
                if old_h == 1500 and old_a == 1500:
                    continue

                new_h, new_a = elo._update_match(old_h, old_a, gh, ga, ha)
                elo._ratings[home] = new_h
                elo._ratings[away] = new_a

                goal_diff = gh - ga
                elo_changes.append({
                    "team": TEAM_CN.get(home, home),
                    "old": round(old_h, 1),
                    "new": round(new_h, 1),
                    "delta": round(new_h - old_h, 1),
                    "delta_signed": f"{new_h - old_h:+.1f}",
                    "reason": f"{gh}-{ga} {'胜' if goal_diff > 0 else '平' if goal_diff == 0 else '负'}",
                })
                elo_changes.append({
                    "team": TEAM_CN.get(away, away),
                    "old": round(old_a, 1),
                    "new": round(new_a, 1),
                    "delta": round(new_a - old_a, 1),
                    "delta_signed": f"{new_a - old_a:+.1f}",
                    "reason": f"{ga}-{gh} {'胜' if goal_diff < 0 else '平' if goal_diff == 0 else '负'}",
                })

        elo.save()
        n_updated = len(set(c["team"] for c in elo_changes))
        print(f"[OK] ELO 已更新 {n_updated} 支球队 ({len(elo_changes)} 条记录)")

    # ---- 更新跟踪 ----
    from pipeline.reporter import update_tracking_file, TEAM_CN

    elo_summary = {"teams_updated": len(set(c["team"] for c in elo_changes))} if elo_changes else None
    tracking = update_tracking_file(matched, date_str, output_dir, elo_summary)

    # ---- 多维度复盘(v1.0) ----
    from pipeline.dimension_review import (
        evaluate_dimensions,
        update_ledger,
        print_dimension_summary,
        load_matches_info,
    )
    matches_info = load_matches_info(date_str)
    day_dims = evaluate_dimensions(new_matched, matches_info)
    ledger_path = os.path.join(state_dir, "dimension_ledger.json")
    ledger = update_ledger(day_dims, ledger_path, date_str=date_str)
    dim_summary = print_dimension_summary(day_dims, ledger)
    print(f"\n[OK] 维度成绩已累计 → {ledger_path}")
    print(dim_summary)

    # ---- 投注结算 (Phase 5 P&L 账本) ----
    from pipeline.pnl_ledger import settle_bets_for_date, format_pnl_summary
    pnl_result = settle_bets_for_date(date_str, matched, state_dir)
    print("\n" + format_pnl_summary(pnl_result))

    # ---- 记录新增场次键 (增量幂等) ----
    if new_matched:
        cur = review_state["dates"].get(date_str) or []
        review_state["dates"][date_str] = sorted(set(cur) | {_mkey(m) for m in new_matched})
        with open(review_state_path, "w", encoding="utf-8") as f:
            json.dump(review_state, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已记录 {len(review_state['dates'][date_str])} 场处理状态")

    # ---- 生成复盘报告 (含维度成绩) ----
    from pipeline.reporter import generate_review_report, update_tracking_file, TEAM_CN

    review_path = generate_review_report(
        matched,
        output_dir=output_dir,
        date_str=date_str,
        elo_changes=elo_changes,
        dimension_summary=dim_summary,
        pnl_text=format_pnl_summary(pnl_result),
    )

    # ---- 复盘分析页 (预测vs结果逐条对账 + LLM错因归因) ----
    try:
        from pipeline.review_analyst import generate_review_analysis
        ra_path = generate_review_analysis(date_str, matched, output_dir=output_dir)
        print(f"[复盘分析] {ra_path}")
    except Exception as e:
        print(f"[复盘分析] 生成失败: {e}")

    # ---- 打印总结 (Phase 1 A2: 无信号场次不计入准确率) ----
    sig = [m for m in matched if not m.get("no_signal")]
    n = len(sig)
    n_nosig = len(matched) - n
    correct = sum(1 for m in sig if
        max(("H", m["predicted"]["home_win"]), ("D", m["predicted"]["draw"]),
            ("A", m["predicted"]["away_win"]), key=lambda x: x[1])[0] == m["actual"])
    brier = sum(
        sum((p - a) ** 2 for p, a in zip(
            [m["predicted"]["home_win"], m["predicted"]["draw"], m["predicted"]["away_win"]],
            {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}[m["actual"]]
        )) / 3
        for m in sig
    ) / n if n > 0 else 1.0

    hh = sum(1 for m in sig if m["actual"] == "H" and
             max(("H", m["predicted"]["home_win"]), ("D", m["predicted"]["draw"]),
                 ("A", m["predicted"]["away_win"]), key=lambda x: x[1])[0] == "H")
    dd = sum(1 for m in sig if m["actual"] == "D" and
             max(("H", m["predicted"]["home_win"]), ("D", m["predicted"]["draw"]),
                 ("A", m["predicted"]["away_win"]), key=lambda x: x[1])[0] == "D")
    aa = sum(1 for m in sig if m["actual"] == "A" and
             max(("H", m["predicted"]["home_win"]), ("D", m["predicted"]["draw"]),
                 ("A", m["predicted"]["away_win"]), key=lambda x: x[1])[0] == "A")

    print(f"\n{'='*60}")
    print(f"复盘总结 — {date_str}")
    print(f"{'='*60}")
    if n_nosig > 0:
        print(f"  无信号场次: {n_nosig} 场 (无赔率冷启动, 不计入以下指标)")
    print(f"  有效场次:  {n}")
    print(f"  Brier:     {brier:.4f}")
    print(f"  准确率:    {correct}/{n} ({correct/n:.1%})" if n > 0 else "  准确率:    n/a")
    print(f"  方向:     主={hh} 平={dd} 客={aa}")
    if tracking.get("cumulative"):
        c = tracking["cumulative"]
        print(f"  历史累计:  {c['total_matches']} 场, Brier {c['avg_brier']:.4f}, Acc {c['avg_accuracy']:.1%}")
    print(f"  复盘报告:  {review_path}")
    print(f"  跟踪文件:  {os.path.join(output_dir, 'daily_tracking.json')}")


def cmd_summary(args):
    """Print model training summary."""
    state_dir = args.state_dir or "data/state"
    summary_path = os.path.join(state_dir, "training_summary.json")

    if not os.path.exists(summary_path):
        print("无训练摘要。先运行 'train'。")
        return

    with open(summary_path, "r", encoding="utf-8") as f:
        s = json.load(f)

    print(f"Training Summary")
    print(f"{'='*60}")
    print(f"Total matches:  {s['total_matches']}")
    print(f"ELO teams:      {s['elo']['teams']}")
    print(f"DC teams:       {s['dc_teams']}")
    print(f"Leagues:        {', '.join(s['leagues'])}")
    print(f"Fit method:     {s['fit_method']}")
    print(f"\nELO Stats:")
    print(f"  Range: {s['elo']['min']} – {s['elo']['max']}")
    print(f"  Mean:  {s['elo']['mean']}")
    print(f"\nTop 10:")
    for team, rating in s['elo']['top_10']:
        print(f"  {team:<25} {rating}")

    # 展示联赛参数
    print("\n联赛参数:")
    for code, params in s.get("league_params", {}).items():
        print(f"  {code}: ρ={params['rho']:.4f}, home_adv={params['home_adv']:.4f}, "
              f"avg_goals={params['avg_goals']}")


def cmd_full(args):
    """Run the complete pipeline: train → backtest → (predict)."""
    print("=" * 60)
    print("完整管线")
    print("=" * 60)

    # Step 1: Train
    print("\n[1/3] 训练")
    cmd_train(args)

    # Step 2: Backtest
    print("\n[2/3] 回测")
    try:
        cmd_backtest(args)
    except SystemExit as e:
        if e.code == 1:
            print("\n管线停止: 回测门禁未通过。")
            return
        raise

    # 第3步: 预测(如带--predict)
    if args.predict_live:
        print("\n[3/3] LIVE PREDICTION")
        cmd_predict(args)
    else:
        print("\n[3/3] 跳过(带--predict才执行预测)")


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()


def _standings_lookup(table, team: str):
    """按队名查积分榜条目 (Phase 7)"""
    if not table or not team:
        return None
    from pipeline.standings_fetcher import lookup
    return lookup(table, team)


def _cs_value(pred: dict, m: dict):
    """波胆价值检测: 模型比分概率 vs 市场波胆赔率 (Phase 10)"""
    cs_odds = m.get("correct_score_odds") or {}
    if not cs_odds:
        return None
    sd = pred.get("score_distribution") or {}
    # 市场隐含概率去水
    implied = {}
    total = 0.0
    for score, odds in cs_odds.items():
        if odds and odds > 1.0:
            ip = 1.0 / odds
            implied[score] = ip
            total += ip
    if total <= 0:
        return None
    values = []
    for score, ip in implied.items():
        fair = ip / total
        mp = sd.get(score, 0.0)
        edge = mp - fair
        if edge >= 0.015 and mp >= 0.02:
            values.append({
                "score": score,
                "model": round(mp, 4),
                "market": round(fair, 4),
                "edge": round(edge, 4),
            })
    values.sort(key=lambda x: -x["edge"])
    return values[:2] if values else None


def _ou_value(pred: dict, m: dict):
    """大小球价值检测: 模型 over25 vs 市场大小球赔率 (Phase 10)"""
    over_odds = m.get("over_odds")
    under_odds = m.get("under_odds")
    if not over_odds or not under_odds:
        return None
    over_imp = 1.0 / over_odds
    under_imp = 1.0 / under_odds
    total = over_imp + under_imp
    if total <= 0:
        return None
    fair_over = over_imp / total
    model_over = pred.get("over_25", 0.0)
    edge = model_over - fair_over
    if abs(edge) < 0.05:
        return None
    side = "大2.5" if edge > 0 else "小2.5"
    return {
        "side": side,
        "model": round(model_over, 4),
        "market": round(fair_over, 4),
        "edge": round(edge, 4),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Football Prediction Pipeline v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  train      Fit ELO + Dixon-Coles from 25 historical CSVs
  backtest   Time-series cross-validation (must beat baseline)
  predict    Generate predictions for today's matches
  review     Evaluate prediction accuracy vs actual results
  full       Run train → backtest → predict in sequence
  summary    Show model state

Examples:
  python pipeline.py train
  python pipeline.py backtest
  python pipeline.py train --mle          # Use scipy MLE fitting
  python pipeline.py predict --matches-json data/today.json
  python pipeline.py review 2026-08-08
  python pipeline.py full --predict
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Common options
    def add_common(p):
        p.add_argument("--csv-dir", default="data/historical_odds", help="CSV directory")
        p.add_argument("--state-dir", default="data/state", help="Model state directory")
        p.add_argument("--output-dir", default="data/output", help="Output directory")

    # train
    p_train = subparsers.add_parser("train", help="Train models from historical data")
    add_common(p_train)
    p_train.add_argument("--mle", action="store_true", default=True,
                        help="Use scipy MLE (requires scipy)")
    p_train.add_argument("--no-mle", action="store_false", dest="mle",
                        help="Use analytical (moment-based) fitting instead")

    # backtest
    p_backtest = subparsers.add_parser("backtest", help="Run time-series backtest")
    add_common(p_backtest)
    p_backtest.add_argument("--force", action="store_true",
                           help="Continue even if backtest gate fails")
    p_backtest.add_argument("--recent-seasons", type=int, default=0,
                           help="实验: 训练只用最近N个赛季 (0=全部)")

    # predict
    p_predict = subparsers.add_parser("predict", help="Generate live predictions")
    add_common(p_predict)
    p_predict.add_argument("--matches-json", help="Path to match list JSON")
    p_predict.add_argument("--llm", action="store_true",
                          help="Add LLM qualitative analysis")
    p_predict.add_argument("--stage", choices=["morning", "midday", "final"], default="final",
                          help="早盘/午盘只出七维分析存档页, 终盘出预测页并注入存档")

    # review
    p_review = subparsers.add_parser("review", help="Evaluate predictions vs results")
    add_common(p_review)
    p_review.add_argument("date", help="Date of predictions (YYYY-MM-DD)")
    p_review.add_argument("--results-json", help="Path to results JSON")
    p_review.add_argument("--results-text", help="Results as text (e.g. 'Arsenal 2-1 Liverpool')")

    # full
    p_full = subparsers.add_parser("full", help="Run complete pipeline")
    add_common(p_full)
    p_full.add_argument("--predict", dest="predict_live", action="store_true",
                       help="Also run live predictions after backtest")
    p_full.add_argument("--mle", action="store_true", default=True, help="Use scipy MLE")

    # summary
    p_summary = subparsers.add_parser("summary", help="Show training summary")
    add_common(p_summary)

    args = parser.parse_args()

    if args.command == "train":
        cmd_train(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "predict":
        cmd_predict(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "full":
        cmd_full(args)
    elif args.command == "summary":
        cmd_summary(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
