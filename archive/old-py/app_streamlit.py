"""
⚽ 足球分析智能体 — Streamlit 前端

启动:
    pip install streamlit
    streamlit run app_streamlit.py

页面:
    🔮 比赛预测  — 单场预测 + 赔率对比 + 价值检测
    🤖 AI 分析   — 对话式深度战术分析
    📊 球队对比  — 雷达图 + 数据面板
    📋 复盘中心  — 昨日回测 + 偏差分析
    📡 实时比分  — 进行中比赛 (需 API)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# 页面配置必须在最前面
st.set_page_config(
    page_title="足球分析智能体",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 确保项目根在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ============================================================
# CSS
# ============================================================

st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; margin-bottom: 0.5rem; }
    .metric-card {
        background: #1e293b; border-radius: 12px; padding: 20px;
        text-align: center; border: 1px solid #334155;
    }
    .metric-value { font-size: 2rem; font-weight: 700; color: #38bdf8; }
    .metric-label { font-size: 0.85rem; color: #94a3b8; margin-top: 4px; }
    .prediction-badge {
        display: inline-block; padding: 6px 18px; border-radius: 20px;
        font-weight: 600; font-size: 1rem;
    }
    .badge-home { background: #065f46; color: #6ee7b7; }
    .badge-draw { background: #713f12; color: #fbbf24; }
    .badge-away { background: #7f1d1d; color: #fca5a5; }
    .value-positive { color: #22c55e; }
    .value-negative { color: #ef4444; }
    .chat-user { background: #1d4ed8; color: white; padding: 10px 16px; border-radius: 12px; margin: 8px 0; }
    .chat-ai { background: #1e293b; border: 1px solid #334155; padding: 12px 16px; border-radius: 12px; margin: 8px 0; line-height: 1.7; }
    hr { border-color: #334155; }
    .sidebar .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 工具函数 (同步包装异步)
# ============================================================

def _run_async(coro):
    """在 Streamlit 中安全运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


@st.cache_resource
def get_agent():
    from src.agent.football_agent import FootballAgent
    return FootballAgent()


@st.cache_resource
def get_pe_agent():
    from src.agent.plan_execute_agent import PlanExecuteAgent
    return PlanExecuteAgent()


# ============================================================
# 侧边栏
# ============================================================

with st.sidebar:
    st.image("https://img.icons8.com/color/96/football2--v1.png", width=64)
    st.markdown("## ⚽ 足球分析智能体")
    st.markdown("---")

    page = st.radio(
        "导航",
        ["🔮 比赛预测", "🤖 AI 深度分析", "📊 球队对比", "📋 复盘中心", "📡 实时比分"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.caption("数据源: API-Football / ELO / Kambi")
    from src.utils.config import config
    has_api = bool(config.FOOTBALL_RAPIDAPI_KEY or config.FOOTBALL_DATA_API_KEY)
    st.caption(f"API 状态: {'🟢 已连接' if has_api else '🟡 模拟数据'}")


# ============================================================
# 页面 1: 比赛预测
# ============================================================

if page == "🔮 比赛预测":
    st.markdown('<p class="main-header">🔮 比赛预测</p>', unsafe_allow_html=True)
    st.caption("泊松分布 × ELO 评分 × Kambi 赔率交叉验证")

    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        home_team = st.text_input("主队 (英文)", value="Arsenal", placeholder="e.g. Arsenal")
    with col2:
        st.markdown("<div style='text-align:center;padding-top:28px;font-size:1.5rem;font-weight:bold;color:#64748b'>VS</div>", unsafe_allow_html=True)
    with col3:
        away_team = st.text_input("客队 (英文)", value="Liverpool", placeholder="e.g. Liverpool")

    c1, c2, c3 = st.columns([2, 1, 2])
    with c1:
        home_form = st.text_input("主队近期战绩", value="W-D-W-W-L", placeholder="W-D-W-W-L")
    with c2:
        league_sel = st.selectbox("联赛", ["PL","PD","BL1","SA","FL1","CL"],
                                   format_func=lambda x: {"PL":"英超","PD":"西甲","BL1":"德甲","SA":"意甲","FL1":"法甲","CL":"欧冠"}.get(x,x))
    with c3:
        away_form = st.text_input("客队近期战绩", value="L-W-D-W-L", placeholder="L-W-D-W-L")

    if st.button("⚡ 开始预测", type="primary", use_container_width=True):
        with st.spinner("模型计算中..."):
            from src.agent.tools import predict_match, compare_model_vs_market

            # 解析 form
            hf = [c.strip() for c in home_form.split("-") if c.strip()] if home_form else None
            af = [c.strip() for c in away_form.split("-") if c.strip()] if away_form else None

            pred = _run_async(predict_match(
                home_team=home_team, away_team=away_team,
                home_form=hf, away_form=af))

            # 赔率对比
            try:
                odds = _run_async(compare_model_vs_market(
                    home_team=home_team, away_team=away_team, competition=league_sel))
            except Exception:
                odds = None

        # --- 概率展示 ---
        st.markdown("---")
        p = pred["prediction"]

        cols = st.columns(3)
        badges = {"主胜": "badge-home", "平局": "badge-draw", "客胜": "badge-away"}
        for i, (label, key) in enumerate([("主胜", "home_win"), ("平局", "draw"), ("客胜", "away_win")]):
            with cols[i]:
                is_rec = p["recommendation"].startswith(label)
                border = "3px solid #38bdf8" if is_rec else "1px solid #334155"
                st.markdown(f"""
                <div class="metric-card" style="border:{border}">
                    <div class="metric-label">{label}</div>
                    <div class="metric-value">{p[key]}%</div>
                    {'<div style="color:#38bdf8;font-weight:600;margin-top:4px">📊 推荐</div>' if is_rec else ''}
                </div>
                """, unsafe_allow_html=True)

        st.markdown(f'<div style="text-align:center;margin:12px 0"><span class="prediction-badge badges-{badges.get(p["recommendation"].split(" ")[0], "badge-home")}">📊 {p["recommendation"]}</span></div>', unsafe_allow_html=True)

        # --- 详细数据 ---
        tab1, tab2, tab3, tab4 = st.tabs(["📊 比分预测", "💰 赔率对比", "📈 球队数据", "🎯 玩法市场"])

        with tab1:
            st.markdown(f"**预期进球**: {home_team} {pred['expected_goals']['home']} — {pred['expected_goals']['away']} {away_team}")
            st.markdown("**最可能比分**:")
            score_cols = st.columns(5)
            for i, s in enumerate(pred["likely_scores"][:5]):
                with score_cols[i]:
                    st.metric(s["score"], s["pct"])

        with tab2:
            if odds:
                va = odds.get("value_analysis", {})
                rec = odds.get("recommendation", {})

                st.markdown("#### 模型 vs 市场")

                comp_cols = st.columns(3)
                sources = [
                    ("模型概率", odds["model_prediction"], "泊松+ELO"),
                    ("市场隐含", odds["market_implied"], "Kambi共识"),
                    ("价值偏差", {
                        "home": va.get("home_value", "0"),
                        "draw": va.get("draw_value", "0"),
                        "away": va.get("away_value", "0"),
                    }, "模型-市场"),
                ]
                for i, (title, data, src) in enumerate(sources):
                    with comp_cols[i]:
                        st.markdown(f"**{title}**")
                        st.caption(src)
                        if isinstance(data, dict):
                            for k in ["home", "draw", "away"]:
                                if k in data:
                                    st.text(f"{k}: {data[k]}")

                st.info(f"**价值判断**: {va.get('verdict', 'N/A')}")
                st.caption(f"Kelly 建议: {va.get('kelly_fraction', 'N/A')} | 置信度: {va.get('confidence', 'N/A')}")
            else:
                st.info("配置 API-Football 可获取实时赔率对比")

        with tab3:
            st.markdown(f"| 指标 | {home_team} | {away_team} |")
            ts = pred.get("team_stats", {})
            for key in ["elo", "attack_strength", "defense_strength", "form_points"]:
                hv = ts.get("home", {}).get(key, "N/A")
                av = ts.get("away", {}).get(key, "N/A")
                st.markdown(f"| {key} | {hv} | {av} |")

        with tab4:
            bm = pred.get("betting_markets", {})
            for label, key in [("大2.5球", "over_2_5_goals"), ("大3.5球", "over_3_5_goals"), ("双方进球", "both_to_score")]:
                st.metric(label, bm.get(key, "N/A"))


# ============================================================
# 页面 2: AI 深度分析
# ============================================================

elif page == "🤖 AI 深度分析":
    st.markdown('<p class="main-header">🤖 AI 深度分析</p>', unsafe_allow_html=True)
    st.caption("UEFA Pro 级别分析师 · 战术知识库 · 多轮对话")

    # 模式选择
    mode = st.radio("分析模式", ["标准 Tool Use", "Plan & Execute"], horizontal=True)

    # 快速问题
    quick_qs = [
        "预测 Arsenal vs Liverpool 的比赛结果",
        "分析曼城边后卫内收战术的优缺点",
        "复盘昨天英超的比赛",
        "对比 Manchester United 和 Chelsea 的攻防能力",
    ]
    st.markdown("**快捷提问:**")
    qcols = st.columns(4)
    selected_q = None
    for i, q in enumerate(quick_qs):
        with qcols[i]:
            if st.button(q[:20] + "...", key=f"qq_{i}", use_container_width=True, help=q):
                selected_q = q

    # 对话历史
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # 输入
    user_input = st.chat_input("输入你的问题...")

    if selected_q:
        user_input = selected_q

    if user_input:
        # 添加用户消息
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("分析中..."):
                if mode == "Plan & Execute":
                    agent = get_pe_agent()
                else:
                    agent = get_agent()

                try:
                    reply = _run_async(agent.chat(user_input))
                except Exception as e:
                    reply = f"❌ 错误: {e}\n\n请确认 .env 中 ANTHROPIC_API_KEY 已正确配置。"

                st.markdown(reply)
                st.session_state.chat_history.append({"role": "assistant", "content": reply})

    # 渲染历史
    for msg in st.session_state.chat_history:
        if msg["role"] != "user" or msg["content"] != st.session_state.chat_history[-1]["content"] if st.session_state.chat_history else True:
            pass  # 已经渲染过最新的


# ============================================================
# 页面 3: 球队对比
# ============================================================

elif page == "📊 球队对比":
    st.markdown('<p class="main-header">📊 球队对比</p>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        team_a = st.text_input("球队 A", value="Arsenal")
    with c2:
        team_b = st.text_input("球队 B", value="Liverpool")

    league_comp = st.selectbox("联赛", ["英超","西甲","德甲","意甲","法甲"], index=0)

    if st.button("🔍 对比分析", type="primary"):
        from src.agent.tools import get_team_statistics, generate_radar_chart

        col_a, col_b = st.columns(2)

        with col_a:
            with st.spinner(f"获取 {team_a} 数据..."):
                stats_a = _run_async(get_team_statistics(team_a, "PL" if league_comp == "英超" else "PD"))
            st.subheader(team_a)
            if "stats" in stats_a:
                sts = stats_a["stats"]
                st.metric("场均进球", sts.get("goals_for_avg", "N/A"))
                st.metric("场均失球", sts.get("goals_against_avg", "N/A"))
                st.metric("射门/场", sts.get("avg_shots", "N/A"))
                st.metric("近期状态", sts.get("form", "N/A"))
            else:
                st.info(str(stats_a.get("estimated", {})))

        with col_b:
            with st.spinner(f"获取 {team_b} 数据..."):
                stats_b = _run_async(get_team_statistics(team_b, "PL" if league_comp == "英超" else "PD"))
            st.subheader(team_b)
            if "stats" in stats_b:
                sts = stats_b["stats"]
                st.metric("场均进球", sts.get("goals_for_avg", "N/A"))
                st.metric("场均失球", sts.get("goals_against_avg", "N/A"))
                st.metric("射门/场", sts.get("avg_shots", "N/A"))
                st.metric("近期状态", sts.get("form", "N/A"))
            else:
                st.info(str(stats_b.get("estimated", {})))

        # 雷达图
        st.markdown("---")
        st.subheader("🕸️ 能力雷达图")
        with st.spinner("生成雷达图..."):
            radar = _run_async(generate_radar_chart(team_a, team_b, output_format="base64"))
            if "chart_base64" in radar:
                import base64
                img_bytes = base64.b64decode(radar["chart_base64"])
                st.image(img_bytes, caption=f"{team_a} vs {team_b}", use_container_width=True)
            elif "error" in radar:
                st.warning(radar["error"] + " (可安装: pip install matplotlib)")
            else:
                # 简单柱状图替代
                import plotly.express as px
                import pandas as pd

                dims = ["进攻火力","防守稳固","控球组织","纪律性","终结效率","近期状态"]
                vals_a = [radar["team"][d] for d in ["attack","defense","possession","discipline","efficiency","form"]]
                vals_b = [radar.get("compare", {}).get(d, 0) for d in ["attack","defense","possession","discipline","efficiency","form"]] if radar.get("compare") else None

                df = pd.DataFrame({"维度": dims * 2, "评分": vals_a + (vals_b or vals_a),
                                   "球队": [team_a]*6 + ([team_b]*6 if vals_b else [team_a]*6)})
                fig = px.bar(df, x="维度", y="评分", color="球队", barmode="group",
                             color_discrete_map={team_a: "#38bdf8", team_b: "#f472b6"})
                fig.update_layout(paper_bgcolor="#0f172a", plot_bgcolor="#0f172a",
                                  font_color="white")
                st.plotly_chart(fig, use_container_width=True)


# ============================================================
# 页面 4: 复盘中心
# ============================================================

elif page == "📋 复盘中心":
    st.markdown('<p class="main-header">📋 复盘中心</p>', unsafe_allow_html=True)
    st.caption("模型 vs 真实赛果 vs Kambi 赔率")

    league_r = st.selectbox("联赛", ["PL","PD","BL1","SA","FL1"],
                            format_func=lambda x: {"PL":"英超","PD":"西甲","BL1":"德甲","SA":"意甲","FL1":"法甲"}.get(x,x))

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("📅 复盘昨日比赛", type="primary", use_container_width=True):
            with st.spinner("复盘分析中..."):
                from src.models.backtest import review_and_adjust
                report = _run_async(review_and_adjust(league_r))

                # 指标卡片
                st.markdown("---")
                mcols = st.columns(4)
                m = report["metrics"]
                with mcols[0]: st.metric("Brier Score", m["brier_score"],
                                         delta="✅" if m["brier_score"] < 0.20 else "⚠️")
                with mcols[1]: st.metric("准确率", m["accuracy"])
                with mcols[2]: st.metric("校准", m["calibration"])
                with mcols[3]:
                    mvm = report.get("model_vs_market", {})
                    st.metric("vs 市场", mvm.get("model_vs_market_gap", "N/A"))

                # 偏差
                st.markdown("#### 系统性偏差")
                bcols = st.columns(3)
                biases = report["biases"]
                with bcols[0]: st.metric("主胜偏差", biases["home_overestimation"])
                with bcols[1]: st.metric("平局偏差", biases["draw_underestimation"])
                with bcols[2]: st.metric("客胜偏差", biases["away_overestimation"])

                # 调整建议
                st.markdown("#### 调整建议")
                for rec in report.get("recommendations", []):
                    icon = "✅" if rec.startswith("✅") else "🔧" if rec.startswith("🔧") else "⚠️" if rec.startswith("⚠️") else "ℹ️"
                    st.markdown(f"{icon} {rec}")

                # 调整因子
                adj = report.get("adjustment_factors", {})
                if adj:
                    st.markdown("#### 建议调整系数")
                    st.json(adj)

                # 逐场
                st.markdown("#### 逐场明细")
                for m in report.get("match_details", []):
                    st.markdown(f"{m['correct']} {m['match']} | 实际: {m['actual']} | 预测: {m['model_predicted']} | {m['model_probs']}")

    with col2:
        st.markdown("#### 🔬 单场回测")
        bt_home = st.text_input("主队", key="bt_home", placeholder="Arsenal")
        bt_away = st.text_input("客队", key="bt_away", placeholder="Chelsea")
        bcols = st.columns(2)
        with bcols[0]:
            bt_hg = st.number_input("主队进球", 0, 10, key="bt_hg")
        with bcols[1]:
            bt_ag = st.number_input("客队进球", 0, 10, key="bt_ag")

        if st.button("回测单场", use_container_width=True):
            from src.agent.tools import backtest_match
            result = _run_async(backtest_match(bt_home, bt_away, bt_hg, bt_ag))
            st.json(result)


# ============================================================
# 页面 5: 实时比分
# ============================================================

elif page == "📡 实时比分":
    st.markdown('<p class="main-header">📡 实时比分</p>', unsafe_allow_html=True)

    live_league = st.selectbox("联赛筛选", ["全部","英超","西甲","德甲","意甲","法甲","欧冠"])

    if st.button("🔄 刷新实时比分", type="primary"):
        from src.agent.tools import get_live_scores

        lg = None if live_league == "全部" else live_league
        with st.spinner("获取中..."):
            scores = _run_async(get_live_scores(league=lg))

        live_matches = scores.get("live_matches", [])
        if not live_matches:
            st.info(scores.get("message", "当前没有进行中的比赛"))
        else:
            st.markdown(f"**{len(live_matches)} 场进行中** · {scores.get('source', '')}")
            st.markdown("---")
            for m in live_matches:
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                with col1:
                    st.markdown(f"**{m['home_team']}** vs **{m['away_team']}**")
                    st.caption(f"{m.get('competition', '')} · {m.get('status', '')}")
                with col2:
                    st.markdown(f"### {m['score']}")
                with col3:
                    st.metric("时间", f"{m.get('elapsed', 0)}'")
                with col4:
                    st.caption(m.get("status", ""))

                st.markdown("---")


# ============================================================
# 页脚
# ============================================================

st.sidebar.markdown("---")
st.sidebar.caption(f"v1.0 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
