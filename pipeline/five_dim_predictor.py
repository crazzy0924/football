"""五维预测器 · v3.0 — 胜平负/让球/大小球/波胆 (半场+角球需新数据)"""
from __future__ import annotations
import json
from pathlib import Path


def compute_handicap_probs(score_dist: dict[str, float], goal_line: float) -> dict:
    """从比分分布计算让球盘概率.

    goal_line: 体彩让球数，如 -1 表示主队让1球, +1 表示客队让1球

    体彩HHAD规则：
    - 主队让-1球: 主队净胜≥2 → 主胜; 主队净胜1 → 平; 否则 → 客胜
    - 主队受让+1球: 主队不败 → 主胜; 客队净胜1 → 平; 客队净胜≥2 → 客胜
    """
    p_cover = p_push = p_lose = 0.0

    for score, prob in score_dist.items():
        hg, ag = map(int, score.split('-'))
        adj_diff = hg - ag + goal_line  # 调整后的净胜球

        if adj_diff > 0:
            p_cover += prob
        elif adj_diff == 0:
            p_push += prob
        else:
            p_lose += prob

    return {
        'goal_line': goal_line,
        'home_cover': round(p_cover, 4),
        'push': round(p_push, 4),
        'away_cover': round(p_lose, 4),
    }


def compute_totals_probs(score_dist: dict[str, float]) -> dict:
    """从比分分布计算总进球数概率分布."""
    totals = {}
    for score, prob in score_dist.items():
        hg, ag = map(int, score.split('-'))
        tg = hg + ag
        totals[tg] = totals.get(tg, 0) + prob

    # 常见盘口
    over_15 = sum(p for tg, p in totals.items() if tg >= 2)
    over_25 = sum(p for tg, p in totals.items() if tg >= 3)
    over_35 = sum(p for tg, p in totals.items() if tg >= 4)
    over_45 = sum(p for tg, p in totals.items() if tg >= 5)

    return {
        'total_goals_dist': {str(k): round(v, 4) for k, v in sorted(totals.items())},
        'over_1_5': round(over_15, 4),
        'over_2_5': round(over_25, 4),
        'over_3_5': round(over_35, 4),
        'over_4_5': round(over_45, 4),
        'expected_goals': round(sum(k * v for k, v in totals.items()), 2),
    }


def compute_correct_score_top(score_dist: dict[str, float], top_n: int = 10) -> list:
    """从比分分布提取最可能波胆."""
    sorted_scores = sorted(score_dist.items(), key=lambda x: x[1], reverse=True)
    return [{'score': s, 'prob': round(p, 4)} for s, p in sorted_scores[:top_n]]


def analyze_hhad_edge(model_probs: dict, market_odds: dict) -> dict:
    """分析让球盘模型 vs 市场差异."""
    if not market_odds:
        return {'edge': 0, 'best_pick': 'skip', 'confidence': 'none'}

    # 体彩HHAD赔率 → 隐含概率 (去水归一化; 键名与ah_odds一致: home/draw/away)
    h_imp = 1.0 / float(market_odds.get('home', market_odds.get('h', 999)))
    d_imp = 1.0 / float(market_odds.get('draw', market_odds.get('d', 999)))
    a_imp = 1.0 / float(market_odds.get('away', market_odds.get('a', 999)))
    total = h_imp + d_imp + a_imp
    h_imp /= total
    d_imp /= total
    a_imp /= total

    edges = {
        'home': model_probs['home_cover'] - h_imp,
        'push': model_probs['push'] - d_imp,
        'away': model_probs['away_cover'] - a_imp,
    }

    best = max(edges, key=edges.get)
    best_edge = edges[best]

    if best_edge > 0.08:
        conf = 'high'
    elif best_edge > 0.03:
        conf = 'medium'
    else:
        conf = 'low'

    return {
        'edges': {k: round(v, 4) for k, v in edges.items()},
        'market_implied': {'home': round(h_imp, 4), 'draw': round(d_imp, 4), 'away': round(a_imp, 4)},
        'best_pick': best,
        'edge': round(best_edge, 4),
        'confidence': conf,
        'kelly': round(max(0, best_edge), 4),
    }


def analyze_ttg_edge(model_totals: dict, market_ttg: dict) -> dict:
    """分析大小球模型 vs 市场差异.

    market_ttg: 体彩TTG赔率 {s0, s1, s2, ..., s7}
    """
    if not market_ttg:
        return {'edge': 0, 'best_pick': 'skip', 'confidence': 'none'}

    # 从TTG赔率计算市场隐含的over/under概率
    raw_imps = {}
    for i in range(8):
        key = f's{i}'
        if key in market_ttg:
            raw_imps[i] = 1.0 / float(market_ttg[key])

    total = sum(raw_imps.values())
    market_goals_dist = {k: v / total for k, v in raw_imps.items()}

    # 市场 over/under 概率
    market_over_15 = sum(p for g, p in market_goals_dist.items() if g >= 2)
    market_over_25 = sum(p for g, p in market_goals_dist.items() if g >= 3)
    market_over_35 = sum(p for g, p in market_goals_dist.items() if g >= 4)

    edges = {
        'over_2_5': model_totals['over_2_5'] - market_over_25,
        'over_3_5': model_totals['over_3_5'] - market_over_35,
    }

    # 找最优方向
    best_key = max(edges, key=edges.get)
    best_edge = edges[best_key]

    if best_edge > 0.08:
        conf = 'high'
    elif best_edge > 0.03:
        conf = 'medium'
    else:
        conf = 'low'

    return {
        'edges': {k: round(v, 4) for k, v in edges.items()},
        'market_implied_over_25': round(market_over_25, 4),
        'market_implied_over_35': round(market_over_35, 4),
        'best_pick': best_key,
        'edge': round(best_edge, 4),
        'confidence': conf,
        'kelly': round(max(0, best_edge), 4),
    }


def generate_five_dim_predictions(predictions_json: str, lottery_json: str, matches_json: str = None) -> list[dict]:
    """从预测JSON + 彩票JSON生成五维预测."""
    with open(predictions_json, 'r', encoding='utf-8') as f:
        preds = json.load(f)

    with open(lottery_json, 'r', encoding='utf-8') as f:
        lottery_data = json.load(f)

    # 用 today_matches_v3.json 做中英文桥接
    en_to_cn = {}
    if matches_json:
        with open(matches_json, 'r', encoding='utf-8') as f:
            matches = json.load(f)
        for m in matches:
            key = (m['home_team'], m['away_team'])
            en_to_cn[key] = (m.get('home_cn', ''), m.get('away_cn', ''))

    # 索引彩票数据按日期
    aug9_matches = lottery_data.get('2026-08-09', [])
    # 用中文队名建索引
    lottery_by_teams = {}
    for lm in aug9_matches:
        key = (lm['homeTeam'], lm['awayTeam'])
        lottery_by_teams[key] = lm

    results = []
    for p in preds:
        m = p['model']
        sd = m.get('score_distribution', {})
        h_en = p['home_team']
        a_en = p['away_team']

        # 通过英文名找中文名
        cn_names = en_to_cn.get((h_en, a_en), (h_en, a_en))
        h_cn, a_cn = cn_names

        # 找彩票数据
        lottery_match = lottery_by_teams.get((h_cn, a_cn))
        hhad_odds = lottery_match.get('hhad') if lottery_match else None
        ttg_odds = lottery_match.get('ttg') if lottery_match else None
        had_odds = lottery_match.get('had') if lottery_match else None

        # ── 维度1: 胜平负 (已有) ──
        dim_1x2 = {
            'home': m['home_win'],
            'draw': m['draw'],
            'away': m['away_win'],
            'market_odds': had_odds,
        }

        # ── 维度2: 让球 ──
        goal_line = 0
        if hhad_odds:
            gl = hhad_odds.get('goalLine', '0')
            try:
                goal_line = float(gl)
            except ValueError:
                goal_line = 0

        handicap = compute_handicap_probs(sd, goal_line)
        hhad_analysis = analyze_hhad_edge(handicap, hhad_odds)

        # ── 维度3: 大小球 ──
        totals = compute_totals_probs(sd)
        ttg_analysis = analyze_ttg_edge(totals, ttg_odds)

        # ── 维度4: 波胆 ──
        correct_scores = compute_correct_score_top(sd, top_n=8)

        # ── 汇总 ──
        result = {
            'home_team': p['home_team'],
            'away_team': p['away_team'],
            'home_cn': h_cn,
            'away_cn': a_cn,
            'league_code': p['league_code'],
            'cold_start': p['cold_start'],
            'elo_home': p['elo_home'],
            'elo_away': p['elo_away'],
            'match_num': lottery_match.get('matchNumStr', '') if lottery_match else '',
            'kickoff': f"{lottery_match.get('matchDate', '')}T{lottery_match.get('matchTime', '')}" if lottery_match else '',
            # 四维预测
            'dim_1x2': dim_1x2,
            'dim_handicap': {
                **handicap,
                'market_odds': hhad_odds,
                'analysis': hhad_analysis,
            },
            'dim_totals': {
                **totals,
                'market_ttg': ttg_odds,
                'analysis': ttg_analysis,
            },
            'dim_correct_score': correct_scores,
            # 贝叶斯后验
            'bayesian': p.get('bayesian'),
            'value': p.get('value'),
        }
        results.append(result)

    return results


# ── CLI ──
if __name__ == '__main__':
    import sys
    results = generate_five_dim_predictions(
        'data/output/predictions_2026-08-09.json',
        'data/lottery_official_parsed_20260808.json',
        'data/today_matches_v3.json'
    )

    with open('data/output/five_dim_2026-08-09.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'Generated {len(results)} five-dim predictions')
    for r in results[:3]:
        print(f"  {r['home_cn']} vs {r['away_cn']}")
        print(f"    让球{r['dim_handicap']['goal_line']}: 主{r['dim_handicap']['home_cover']:.1%} 走{r['dim_handicap']['push']:.1%} 客{r['dim_handicap']['away_cover']:.1%}")
        print(f"    大小球: O2.5={r['dim_totals']['over_2_5']:.1%} O3.5={r['dim_totals']['over_3_5']:.1%}")
        scores_str = ', '.join(f"{s['score']}({s['prob']:.1%})" for s in r['dim_correct_score'][:4])
        print(f"    波胆: {scores_str}")
        print()
