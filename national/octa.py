# -*- coding: utf-8 -*-
"""八维盲判分析师 (国家队版) —— 两段式, 先判断后看价。

为什么不是"调权重" (2026-09-24 我自己想清楚的):
  原来的方案是把市场权重从 20 降到 5。**那是错的** —— 同一天刚刚证明:
  挪威那场市场是对的, 我们错在没看到"丹麦危机 + 埃里克森缺阵"。给市场降权只会让我们更错。

  真正的问题不是权重, 是**顺序**。现有框架(见 pipeline/analyst.py)是"先给赔率、再打分",
  还有一条"情报/赔率/预警两方反对就必须下调方向分"——那不叫分析, 那叫解释赔率。

  所以这里改成两段式:
    第一段 **遮住赔率**做八维 -> 冻结方向分与比分 (市场维度权重 = 0)
    第二段 揭开赔率 -> **只允许因为"市场揭示了一个我确实漏掉的具体事实"而改判**,
           且必须白纸黑字写下那个事实是什么
    第三段 落账 -> 赛前锁死, 赛后打分 (national/calls_ledger.jsonl)

这样"我们自己的那套判断"是真实存在的, 不是调参调出来的。
"""
import json, math, os, re, sys, time
from collections import Counter
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

LEDGER = os.path.join(_ROOT, "data", "national", "calls_ledger.jsonl")

# 提示词/评分逻辑一改就必须改这个字符串。
# 台账里每条的 prompt_version 决定它是不是"当前口径"下的判断。
PROMPT_VERSION = "octa-v2-2026-09-24"


def _next_revision(business_date: str, home: str, away: str) -> int:
    """同一场比赛的第几次判断。**台账不可改**, 所以重复跑只能追加, 靠 revision 区分。

    评分时必须只取每场 revision 最大的那条 —— 否则同场多条会被算重。
    开场前反复修订是允许的 (开赛后禁止再落账)。
    """
    if not os.path.exists(LEDGER):
        return 1
    n = 0
    with open(LEDGER, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if (r.get("business_date") == business_date and r.get("home") == home
                    and r.get("away") == away):
                n = max(n, int(r.get("revision", 0) or 0))
    return n + 1

# ── 第一段权重: 市场 = 0 (遮住), 其余按"我们的信息在哪里"重分 ──
WEIGHTS_S1 = [
    ("状态攻防", 22),
    ("阵容伤停", 24),   # 我们的差异化信息几乎全在这
    ("交锋克制", 8),
    ("赛程体能", 8),    # 已用 15,620 场证明无信号, 低权重但仍作背景
    ("天气场地", 7),
    ("裁判", 5),
    ("战意轮换", 26),   # 本届挂钩 2028 欧洲杯附加赛; 模型完全无此信号
]
# 合计 100; 市场在第二段以"对照"身份出现, 不进第一段的方向分

INSTRUCTION_S1 = """你是资深足球赛前分析师, 正在**独立**判断一场欧国联的比赛。
(2026-09-26 起范围扩大: A/B/C 级都做。**不要默认这是强强对话** ——
 先看证据里的模型概率/ELO/排名, 判断这是同档对撞还是强弱分明, 再下判断。
 级别只影响你的背景预期, 不要因为"是 C 级"就降低对具体证据的权重。)

**重要: 你看不到赔率。这是故意的。** 请只根据证据形成你自己的判断, 不要揣测"市场会怎么看"。
你的价值在于**有自己的观点**, 而不是复述一个你还没看到的共识。

请按七维(第八维"市场"本轮缺席)做定性评估, 输出**方向分**与**比分**:

1. 状态与攻防: 模型概率/预期进球/ELO差/近期战绩 — 反映实力与状态
2. 阵容与伤停: **必须区分核心主力与替补**; 情报写"折损高/中/低"时按其量化影响; 情报没提就写"未获取, 权重记0", **禁止编造**
3. 交锋与克制: 结合双方阵容变化程度 — 换帅/大换血时**必须主动降权**
4. 赛程与体能: 休息天数、窗口密度、轮换概率
5. 天气与场地: 有情报才评, 没有写"未获取, 权重记0"
6. 裁判: 有任命才评, 没有写"未获取, 权重记0"
7. 战意与轮换: 结合小组形势与升降级/出线代价

权重 (合计100): 状态攻防22 / 阵容伤停24 / 交锋克制8 / 赛程体能8 / 天气场地7 / 裁判5 / 战意轮换26
天气或裁判无情报时, 把对应权重按比例分给"阵容伤停"和"战意轮换", 并注明。

**判断纪律 (这是本次分析的核心, 违反即失败)**:
- 你必须**明确站边**。三选一: 主胜 / 平局 / 客胜。**不许用"略占优势""需谨慎"这类话糊过去。**
- 你必须给一个**具体的最终比分**, 以及一条**你认真考虑过的备选比分**。
- 冷门方向如果证据支持, 就大胆写。**不要因为"对方更强"就自动滑向强队。**
- 但如果证据确实指向热门, 也如实写热门 —— **独立不等于唱反调**。
- 情报不足就写"数据不足已降权", 禁止编造伤停/天气/裁判/数字。
- 概率数字只能用证据包里给的, 不许自己造。
- 结论方向必须与最终比分的方向一致。

输出格式 (只输出一个合法JSON对象, 不要代码块标记, 不要投注建议):

{
  "站边": "主胜/平局/客胜 三选一",
  "比分": "最终比分, 如2-1",
  "备选比分": "认真考虑过的另一条, 如1-1",
  "置信度分": 0到100的整数, 表示你对"站边"这一项的把握,
  "这场的形状": "一句话说清这是什么类型的比赛 (对攻/闷战/一方崩盘/拉锯等), 40字内",
  "七维": [
    {"维度":"状态攻防", "证据":"1-2条关键证据, 带日期或来源", "优势分":0, "权重":22, "置信度":"高/中/低", "研判":"该维度如何影响本场"},
    {"维度":"阵容伤停", "证据":"...", "优势分":0, "权重":24, "置信度":"...", "研判":"..."},
    {"维度":"交锋克制", "证据":"...", "优势分":0, "权重":8, "置信度":"...", "研判":"..."},
    {"维度":"赛程体能", "证据":"...", "优势分":0, "权重":8, "置信度":"...", "研判":"..."},
    {"维度":"天气场地", "证据":"...", "优势分":0, "权重":7, "置信度":"...", "研判":"..."},
    {"维度":"裁判", "证据":"...", "优势分":0, "权重":5, "置信度":"...", "研判":"..."},
    {"维度":"战意轮换", "证据":"...", "优势分":0, "权重":26, "置信度":"...", "研判":"..."}
  ],
  "路径": {
    "常规": {"触发":"触发条件", "比分":["2-0","1-0"]},
    "平局": {"触发":"触发条件", "比分":["1-1","0-0"]},
    "冷门": {"触发":"冷门成立的可验证条件", "比分":["0-1"]}
  },
  "最大风险": "这个判断最可能怎么被打脸, 一句话",
  "触发器": ["赛前什么变化会推翻我的结论, 最多3条"]
}

规则:
- 七维必须恰好7项, 顺序固定; 权重合计必须等于100。
- **优势分的正负号定义 (极易搞错, 2026-09-24 实测栽过)**:
    正值 = 这个维度**对主队有利**;  负值 = 对客队有利;  0 = 中立/无信息。
    例: 主队核心停赛 -> 阵容伤停维度给 **负数**;  客队新帅首战 -> 给 **负数**;
    主队主场气氛极强 -> 给 **正数**。
    **不要**用"证据强度"当优势分 —— 证据再强, 也要问它帮的是哪一边。
- 最终方向完全由这些优势分决定, 所以你给的分必须支持你选的站边。
  如果你选客胜, 加权和就该是负的。**自相矛盾的输出会被程序判为不合格。**
- 优势分为 -5 至 +5 的整数。
- **不要输出方向分。** 方向分会由程序按 Σ(优势分×权重)÷100 计算 ——
  你上一版自己算的那个数, 6 场里 4 场算错(其中一场符号都反了), 所以这个权力被收回了。
- 你要保证的是:**每个维度的优势分是你真实的意思**, 因为最终方向完全由它们决定。
- 置信度分要有区分度: 证据扎实、维度一致时给高分; 情报缺项多、维度互相矛盾时给低分。
  **不要一律给 50-60。**
"""

INSTRUCTION_S2 = """你是同一位分析师。上一轮你在**看不到赔率**的情况下已经形成了独立判断。
现在赔率揭晓了。请做第二段工作。

**核心纪律: 你的默认立场是"我的判断成立"。** 市场和我不同, 不代表市场对。
**你只允许在一种情况下改判**: 市场让我意识到一个**我上一轮确实漏掉的具体事实**
(例如: 我漏看了某队核心停赛 / 我漏看了这是新帅首战 / 我漏看了场地改到中立场)。

严禁的改判理由:
- "市场更有信息优势" / "庄家不会错" / "赔率这么开一定有道理"  —— 这些都不是事实, 是借口
- "为了稳健起见" / "降低风险"                                     —— 不许对冲
- 只是因为我上一轮给的方向概率偏低                                  —— 那叫复盘, 不叫改判

若改判, 你**必须**在 "我漏掉的事实" 字段里写清那是什么, 且它必须是**可验证的具体事件**,
不能是"感觉""直觉""市场情绪"。写不出来就不许改判。

输出格式 (只输出一个合法JSON对象):

{
  "市场隐含": "从赔率去水后的主/平/客概率, 直接引用给定的数字",
  "市场与我的关系": "同向 / 反向",
  "是否改判": "否 / 是",
  "我漏掉的事实": "若改判, 写清那个可验证的具体事实; 若不改判, 写 none",
  "分歧说明": "若反向: 我认为谁对、为什么、市场可能错在哪里 (若无分歧写 none)",
  "最终站边": "主胜/平局/客胜",
  "最终比分": "如2-1",
  "最终置信度分": 0到100的整数,
  "反向验证": "如果我错了, 最可能错在哪, 一句话"
}
"""


# ══════════════════════════ 证据包 ══════════════════════════
def _cn(team: str) -> str:
    from national import EN_TO_CN
    return EN_TO_CN.get(team, team)


def recent_form(ms: list[dict], team: str, n: int = 6, since: str = "2025-01-01") -> list[str]:
    got = [m for m in ms if m["date"] >= since and team in (m["home"], m["away"])]
    got.sort(key=lambda m: m["date"], reverse=True)
    out = []
    for m in got[:n]:
        loc = "中" if m["neutral"] else ("主" if m["home"] == team else "客")
        opp = m["away"] if m["home"] == team else m["home"]
        gf, ga = (m["hg"], m["ag"]) if m["home"] == team else (m["ag"], m["hg"])
        out.append("%s %s %s %d-%d %s (%s)" % (m["date"], loc, team, gf, ga, opp, m["tournament"][:22]))
    return out


def h2h(ms: list[dict], a: str, b: str, since: str = "2018-01-01", n: int = 6) -> list[str]:
    got = [m for m in ms if m["date"] >= since and {m["home"], m["away"]} == {a, b}]
    got.sort(key=lambda m: m["date"], reverse=True)
    out = []
    for m in got[:n]:
        out.append("%s %s %d-%d %s [%s %s]" % (m["date"], m["home"], m["hg"], m["ag"], m["away"],
                                               m["tournament"][:20], "中立场" if m["neutral"] else "主场"))
    return out if out else ["近 8 年无交锋记录"]


def slice_intel(date_str: str, home_cn: str, away_cn: str) -> str:
    """从情报文件里切出这场的一节 (按 ## 标题切)。没有就明确说未获取。"""
    p = os.path.join(_ROOT, "data", "national", "intel_%s.txt" % date_str)
    if not os.path.exists(p):
        return "**情报文件不存在 —— 全部情报维度权重记 0, 禁止编造。**"
    text = open(p, encoding="utf-8").read()
    for b in re.split(r"\n(?=## )", text):
        if b.startswith("## ") and home_cn in b and away_cn in b:
            return b.strip()
    return "**这份情报文件里没有本场 —— 全部情报维度权重记 0, 禁止编造。**"


def build_evidence_s1(ms, model, elo, tables, stakes_all, rnd, home, away, date_str) -> str:
    h_cn, a_cn = _cn(home), _cn(away)
    dc = model.predict(home, away, neutral=False, comp="NL")
    dcr = {t: i + 1 for i, (t, *_ ) in enumerate(model.ratings())}
    elr = {t: i + 1 for i, (t, _v) in enumerate(sorted(elo.items(), key=lambda kv: -kv[1]))}
    grp = None
    for g, ts in tables.items():
        if home in ts and away in ts:
            grp = g
    L = []
    L.append("=== 比赛 ===")
    # 2026-09-26: 范围已从"A 级 16 队"扩大到"体彩在售的全部 A/B/C 级场次"。
    # 组号只在联赛内部有意义, 且 B/C 级分组尚未拿到权威源 → 拿不到就写「待核实」,
    # **不编造组号**(组号只影响提示词文字, 不影响任何模型的数字)。
    if grp:
        L.append("%s (%s) vs %s (%s)   欧国联 %s组   第 %d 轮 / 共 6 轮"
                 % (home, h_cn, away, a_cn, grp, rnd + 1))
    else:
        L.append("%s (%s) vs %s (%s)   欧国联 (联赛分组待核实)   第 %d 轮 / 共 6 轮"
                 % (home, h_cn, away, a_cn, rnd + 1))
    L.append("赛制: 分级别多组小组赛; 名次与升级/降级及欧洲杯附加赛资格挂钩。")
    L.append("本届特殊: 9/24-10/6 超长国际窗, 各队 13 天内打 4 场。")
    L.append("")
    L.append("=== 状态攻防 (模型侧数字, 未给结论) ===")
    L.append("DC(Dixon-Coles): 主胜 %.1f%% / 平 %.1f%% / 客胜 %.1f%%"
             % (dc["home_win"] * 100, dc["draw"] * 100, dc["away_win"] * 100))
    L.append("预期进球: %s %.2f - %.2f %s" % (home, dc["lam_h"], dc["lam_a"], away))
    L.append("大小球: 大1.5 %.1f%% / 大2.5 %.1f%% / 大3.5 %.1f%%   双方进球 %.1f%%"
             % (dc["over_15"] * 100, dc["over_25"] * 100, dc["over_35"] * 100, dc["btts"] * 100))
    L.append("模型最可能比分: %s" % ", ".join("%s %.1f%%" % (s, p * 100) for s, p in dc["top_scores"][:4]))
    L.append("ELO: %s %.0f (#%d)  %s %.0f (#%d)  差 %+.0f (含主场加分)"
             % (home, elo.get(home, 1500), elr.get(home, 0), away, elo.get(away, 1500), elr.get(away, 0),
                elo.get(home, 1500) + 100 - elo.get(away, 1500)))
    L.append("DC 强度排名: %s #%d   %s #%d" % (home, dcr.get(home, 0), away, dcr.get(away, 0)))
    L.append("")
    L.append("=== 近期战绩 ===")
    for t, cn in ((home, h_cn), (away, a_cn)):
        L.append("[%s] 近 6 场:" % cn)
        for s in recent_form(ms, t):
            L.append("   " + s)
    L.append("")
    L.append("=== 交锋克制 (近 8 年) ===")
    for s in h2h(ms, home, away):
        L.append("   " + s)
    L.append("")
    L.append("=== 赛程体能 ===")
    L.append("本场是本窗口第 %d 轮。我们自己的回归检验显示休息差分对结果无可用信号" % (rnd + 1))
    L.append("(窗口内 t=-0.07, 系数 -0.0008 球/天), 所以这一维**主要看轮换意愿**, 别靠休息天数推胜负。")
    L.append("")
    L.append("=== 战意轮换 (小组形势) ===")
    for t, cn in ((home, h_cn), (away, a_cn)):
        r = (tables.get(grp) or {}).get(t)
        st = (stakes_all.get(grp) or {}).get(t) or {}
        if r:
            L.append("   %s: %d 场 %d 分 净%+d   形势: %s"
                     % (cn, r["p"], r["pts"], r["gf"] - r["ga"], st.get("note", "-")))
    L.append("")
    L.append("=== 场外情报 (维度2阵容伤停 / 维度5天气场地 / 维度6裁判) ===")
    L.append(slice_intel(date_str, h_cn, a_cn))
    return "\n".join(L)


def build_evidence_s2(s1: dict, mkt: dict) -> str:
    L = ["=== 你上一轮的盲判结果 ==="]
    L.append(json.dumps({k: s1.get(k) for k in ("方向分", "站边", "比分", "备选比分", "置信度分", "这场的形状")},
                        ensure_ascii=False, indent=1))
    L.append("")
    L.append("=== 现在揭晓的赔率 ===")
    L.append("体彩 SPF: %.2f / %.2f / %.2f   (抽水 %.1f%%)"
             % (mkt["odds"][0], mkt["odds"][1], mkt["odds"][2], mkt["margin"] * 100))
    L.append("去水后隐含: 主胜 %.1f%% / 平 %.1f%% / 客胜 %.1f%%"
             % (mkt["probs"][0] * 100, mkt["probs"][1] * 100, mkt["probs"][2] * 100))
    return "\n".join(L)


# ══════════════════════════ LLM ══════════════════════════
def call_llm(prompt: str, system: str) -> str | None:
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(k, None)
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
    except Exception:
        print("  [错误] 读不到 config")
        return None
    if not DEEPSEEK_API_KEY:
        print("  [错误] DEEPSEEK_API_KEY 为空")
        return None
    try:
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=DEEPSEEK_API_KEY, disable_thinking_by_default=True)
        resp = client.chat(model=DEEPSEEK_MODEL,
                           messages=[{"role": "system", "content": system},
                                     {"role": "user", "content": prompt}],
                           max_tokens=3000, temperature=0.35)   # 0.7 时同一场跑出过 3 种结论
        msg = resp.get("message") or {}
        return (msg.get("content") or "").strip() or None
    except Exception as e:
        print("  [错误] LLM 调用失败: %s" % e)
        return None


SYSTEM = "你是资深足球赛前分析师。只输出用户要求的合法JSON对象, 不要代码块标记, 不推荐投注, 不编造。"


def parse_json(text: str) -> dict | None:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except Exception:
        return None


def append_ledger(rec: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ══════════════════════════ 主流程 ══════════════════════════
def main() -> int:
    import argparse
    from national.corpus import load_matches
    from national.dc_national import NationalDC
    from national.elo import compute_elo
    from national.standings import build_tables, rounds_played, stakes
    from national.run_nl import fetch_sporttery, kickoff_abs, CN_TO_EN, ALPHA_TEAM, HALF_LIFE_DAYS

    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--only", default="", help="只跑队名含该字符串的场次")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=3, help="第一段盲判跑几次 (自洽性投票)")
    ap.add_argument("--only-divergent", type=float, default=0.0,
                    help="只跑 |DC模型-市场| >= 该百分点 的场次 (省钱用; 默认 0 = 全跑)")
    ap.add_argument("--dry-run", action="store_true", help="不落账、不写文件")
    args = ap.parse_args()

    now = datetime.now()
    print("=" * 76)
    print("八维盲判分析师 (国家队版)   %s   business_date=%s" % (now.strftime("%Y-%m-%d %H:%M"), args.date))
    print("=" * 76)

    ms = load_matches(since="2016-01-01")
    model = NationalDC(half_life_days=HALF_LIFE_DAYS, alpha_team=ALPHA_TEAM).fit(ms)
    elo, _pre = compute_elo(ms)
    tables = build_tables(ms)
    stakes_all = {g: stakes(tb) for g, tb in tables.items()}
    rnd = max((rounds_played(t) for t in tables.values()), default=0)
    print("语料 %d 场  球队 %d 支  已完成 %d/6 轮" % (len(ms), len(model.teams), rnd))

    raw = fetch_sporttery()
    picks = []
    for m in raw:
        if "欧国联" not in (m["league"] or ""):
            continue
        h = CN_TO_EN.get((m["home_cn"] or "").strip())
        a = CN_TO_EN.get((m["away_cn"] or "").strip())
        if not h or not a:
            continue
        ko = kickoff_abs(m["business_date"], m["match_time"])
        if ko is not None and ko < now:
            continue
        m["home"], m["away"], m["ko"] = h, a, ko
        picks.append(m)
    picks.sort(key=lambda x: x["match_time"])
    if args.only:
        picks = [m for m in picks if args.only in m["home_cn"] or args.only in m["away_cn"]]
    if args.limit:
        picks = picks[:args.limit]
    if args.only_divergent > 0:
        keep = []
        for m in picks:
            had = m.get("had") or {}
            try:
                oh, od, oa = float(had["h"]), float(had["d"]), float(had["a"])
            except Exception:
                continue
            from models.odds import implied_probability
            imp = implied_probability(oh, od, oa)
            dc = model.predict(m["home"], m["away"], neutral=False, comp="NL")
            mp = [imp["home"], imp["draw"], imp["away"]]
            dp = [dc["home_win"], dc["draw"], dc["away_win"]]
            gap = max(abs(dp[i] - mp[i]) for i in range(3)) * 100
            if gap >= args.only_divergent:
                keep.append(m)
                print("   保留 (DC vs 市场差 %.1f 个点): %s vs %s" % (gap, m["home_cn"], m["away_cn"]))
        picks = keep
    print("待分析 League A 场次: %d" % len(picks))
    results = []
    for i, m in enumerate(picks, 1):
        h, a = m["home"], m["away"]
        print()
        print("-" * 76)
        print("[%d/%d] %s vs %s   %s   (%s)"
              % (i, len(picks), m["home_cn"], m["away_cn"], m["num"],
                 m["ko"].strftime("%m-%d %H:%M") if m["ko"] else "?"))
        had = m.get("had") or {}
        try:
            oh, od, oa = float(had["h"]), float(had["d"]), float(had["a"])
        except Exception:
            print("   无体彩赔率, 跳过"); continue
        from models.odds import implied_probability
        imp = implied_probability(oh, od, oa)
        mkt = {"odds": (oh, od, oa), "margin": imp["margin"],
               "probs": (imp["home"], imp["draw"], imp["away"])}

        ev1 = build_evidence_s1(ms, model, elo, tables, stakes_all, rnd, h, a, args.date)
        # ── 第一段 盲判: 跑 K 次取多数 (自洽性投票) ──
        # 2026-09-24 实测: 同一份证据跑 5 次出过 3 种结论 (客胜/主胜/平局)。
        # 一个不稳定的判断不是判断。所以这里把"跑几次一致"本身当成测量值, 直接写进台账。
        print("   第一段 盲判中 (遮住赔率, 跑 %d 次) ..." % args.repeats)
        runs = []
        for k in range(args.repeats):
            raw_k = call_llm(INSTRUCTION_S1 + "\n\n" + ev1, SYSTEM)
            s_k = parse_json(raw_k)
            if not s_k:
                print("     run%d: 解析失败" % (k + 1))
                continue
            dims_k = s_k.get("七维") or []
            try:
                # 方向分由程序算, 不信 LLM 自报的数
                # (2026-09-24: 它 6 场里 4 场算错, 其中一场符号都反了)
                s_k["方向分"] = round(
                    sum(int(d.get("优势分", 0)) * int(d.get("权重", 0)) for d in dims_k) / 100.0, 2)
                s_k["权重合计"] = sum(int(d.get("权重", 0)) for d in dims_k)
            except Exception:
                s_k["方向分"] = None
            dj = s_k.get("方向分") or 0
            s_k["_矛盾"] = ((s_k.get("站边") == "主胜" and dj < -0.3) or
                           (s_k.get("站边") == "客胜" and dj > 0.3))
            runs.append(s_k)
            print("     run%d: %s %s  方向分 %s  置信度分 %s%s"
                  % (k + 1, s_k.get("站边"), s_k.get("比分"), s_k.get("方向分"),
                     s_k.get("置信度分"), "   ⚠ 维度分不支持站边" if s_k["_矛盾"] else ""))
        if not runs:
            print("   ✗ 第一段全部失败, 跳过本场")
            continue
        votes = Counter(r.get("站边") for r in runs)
        winner, agree_n = votes.most_common(1)[0]
        agreement = agree_n / len(runs)
        pool = [r for r in runs if r.get("站边") == winner]
        pool.sort(key=lambda r: (r.get("方向分") is None, r.get("方向分")))
        s1 = pool[len(pool) // 2]          # 取多数派里的中位数那个, 不取极端
        s1["_投票"] = dict(votes)
        s1["_一致度"] = "%d/%d" % (agree_n, len(runs))
        print("   盲判(多数): %s   一致度 %s   方向分 %s   比分 %s   置信度分 %s"
              % (winner, s1["_一致度"], s1.get("方向分"), s1.get("比分"), s1.get("置信度分")))
        print("   形状: %s" % s1.get("这场的形状"))

        ev2 = build_evidence_s2(s1, mkt)
        print("   第二段 对照赔率 ...")
        raw2 = call_llm(INSTRUCTION_S2 + "\n\n" + ev2, SYSTEM)
        s2 = parse_json(raw2) if raw2 else None
        if s2:
            print("   市场: 主 %.1f%% / 平 %.1f%% / 客 %.1f%%   关系: %s"
                  % (mkt["probs"][0] * 100, mkt["probs"][1] * 100, mkt["probs"][2] * 100,
                     s2.get("市场与我的关系")))
            print("   是否改判: %s   %s" % (s2.get("是否改判"),
                  ("漏掉的事实: " + str(s2.get("我漏掉的事实"))) if s2.get("是否改判") == "是" else ""))
            if s2.get("分歧说明") and s2.get("分歧说明") != "none":
                print("   分歧说明: %s" % s2.get("分歧说明"))
            print("   >> 最终: %s  比分 %s  置信度分 %s"
                  % (s2.get("最终站边"), s2.get("最终比分"), s2.get("最终置信度分")))
        else:
            print("   ⚠ 第二段失败, 以盲判为准")

        rec = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_version": PROMPT_VERSION,
            "revision": _next_revision(m["business_date"], h, a),
            "business_date": m["business_date"], "num": m["num"],
            "kickoff_abs": m["ko"].strftime("%Y-%m-%d %H:%M") if m["ko"] else None,
            "home": h, "away": a, "home_cn": m["home_cn"], "away_cn": m["away_cn"],
            "odds": {"h": oh, "d": od, "a": oa},
            "market_probs": {"home": mkt["probs"][0], "draw": mkt["probs"][1], "away": mkt["probs"][2]},
            "stage1_blind": s1,
            "stage2_vs_market": s2,
            "final": {"站边": (s2 or s1).get("最终站边") or s1.get("站边"),
                      "比分": (s2 or s1).get("最终比分") or s1.get("比分"),
                      "置信度分": (s2 or s1).get("最终置信度分") or s1.get("置信度分"),
                      "方向分": s1.get("方向分"),
                      "自洽度": s1.get("_一致度"),
                      "投票": s1.get("_投票")},
            "engine": {"model": "NationalDC", "alpha": ALPHA_TEAM, "half_life": HALF_LIFE_DAYS,
                       "n_matches": len(ms), "w_market_fusion": None, "note": "本记录不经过市场融合"},
        }
        rec["evidence_s1"] = ev1   # 存证据包供事后审计 (只进 octa_*.json, 不进台账)
        results.append(rec)
        if not args.dry_run:
            append_ledger({k: v for k, v in rec.items() if k != "evidence_s1"})

    print()
    print("=" * 76)
    print("汇总 (我们的判断, 未经市场融合)")
    print("  场次                    盲判      -> 最终      比分    市场(主/平/客)")
    for r in results:
        f = r["final"]
        mp = r["market_probs"]
        print("  %-20s  %-6s  ->  %-6s    %-5s   %.0f/%.0f/%.0f"
              % ((r["home_cn"] + " vs " + r["away_cn"])[:20], r["stage1_blind"].get("站边", "?"),
                 f.get("站边", "?"), f.get("比分", "?"),
                 mp["home"] * 100, mp["draw"] * 100, mp["away"] * 100))
    if not args.dry_run and results:
        print()
        print("已落账 %d 条 -> %s" % (len(results), os.path.relpath(LEDGER, _ROOT)))
        out = os.path.join(_ROOT, "data", "national", "octa_%s.json" % args.date)
        json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("完整输出 -> %s" % os.path.relpath(out, _ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())