# -*- coding: utf-8 -*-
"""
克劳德独立交叉核验模块 (整合流水线 · v1.0)

角色: 克劳德是独立定性交叉分析师, 不参与 sky4.0 出数, 只审它的结论。
职责: 对每场五大联赛/欧冠比赛, 抓 sky4.0 的 P0/P1/P2 反向错误, 输出
      同意/保留/反对 + 方向 + 问题等级 + 首选比分 + 大小球。

通道: DeepSeek (deepseek-harness) 优先, Anthropic 回退 (复用 config.py)。
      与 sky4.0 的 analyst.py 同源, 但提示词是「审计」视角, 不是「分析师」视角。

用法:
  python pipeline/claude_cross.py 2026-09-08
  python pipeline/claude_cross.py 2026-09-08 --no-llm   # 只跑结构化检查, 不调 LLM
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path

# Windows GBK 修复 (只在独立运行时包装; 被整合流水线 import 时不碰全局 stdout, 避免双重包装)
def _fix_stdout() -> None:
    if hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "_dsh_utf8", False) is False:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        setattr(sys.stdout, "_dsh_utf8", True)


ROOT = Path(__file__).resolve().parent.parent  # sky日记/ (E:\ 副本)
SKY_DIR = ROOT  # 活量化系统目录, 默认自己; 桥接时可被 --sky-dir 覆盖为 D:\足球大模型1.0
sys.path.insert(0, str(ROOT))


def set_sky_dir(path: str) -> None:
    """指向活量化系统 (D:\足球大模型1.0), 让 config/.env 从活系统加载 (含 DEEPSEEK key)"""
    global SKY_DIR
    SKY_DIR = Path(path)
    sys.path.insert(0, str(SKY_DIR))

# 聚焦范围: 五大联赛 + 欧冠 (董事长的核心关注)
FOCUS_CODES = {"PL", "PD", "BL1", "SA", "FL1", "UCL"}
# 英冠按 2026-09-01 纪律纳入下注信号范围, 但默认不进「我的预测」, 用 --include-elc 开启
LEAGUE_NAMES = {
    "PL": "英超", "PD": "西甲", "BL1": "德甲", "SA": "意甲", "FL1": "法甲",
    "UCL": "欧冠", "UEL": "欧联", "ELC": "英冠", "BL2": "德乙", "FL2": "法乙",
    "DED": "荷甲", "PPL": "葡超", "BSA": "巴甲", "CLB": "解放者杯",
}


def _argmax(d: dict) -> str:
    return max(d, key=d.get) if d else "none"


def _is_chinese(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def dedupe_predictions(preds: list[dict]) -> list[dict]:
    """去重: sky4.0 队名桥接未归一会产生同场重复(中文名 vs 英文名).
    按 (开球时间, 客队英文名) 判同场, 保留中文队名版本."""
    by_key: dict = {}
    order: list = []
    for p in preds:
        ko = (p.get("kickoff_time") or "")[:5]
        away = (p.get("away_team") or "").lower()
        key = (ko, away)
        home = p.get("home_team", "")
        if key not in by_key:
            by_key[key] = p
            order.append(key)
        elif _is_chinese(home) and not _is_chinese(by_key[key].get("home_team", "")):
            by_key[key] = p
    return [by_key[k] for k in order]


def market_direction(odds: dict) -> str:
    """市场方向: 最低赔率方 = 市场最看好 (方向信市场纪律)"""
    if not odds or not odds.get("home") or not odds.get("draw") or not odds.get("away"):
        return "none"
    return _argmax({"home": 1 / odds["home"], "draw": 1 / odds["draw"], "away": 1 / odds["away"]})


def model_direction(model: dict) -> str:
    if not model:
        return "none"
    return _argmax({"home": model.get("home_win", 0), "draw": model.get("draw", 0),
                    "away": model.get("away_win", 0)})


def bayes_direction(bayes: dict) -> str:
    post = (bayes or {}).get("posterior")
    if not post:
        return "none"
    return _argmax({"home": post.get("home", 0), "draw": post.get("draw", 0),
                    "away": post.get("away", 0)})


def pick_direction(pred: dict) -> str:
    """sky4.0 最终显示的看好方向 (bayesian.pick), 归一为 home/draw/away/none"""
    pick = ((pred.get("bayesian") or {}).get("pick") or "").strip().lower()
    if pick.startswith("home"):
        return "home"
    if pick.startswith("away"):
        return "away"
    if pick.startswith("draw"):
        return "draw"
    return bayes_direction(pred.get("bayesian") or {})


def structural_flags(pred: dict) -> list[str]:
    """结构化预检 (不靠 LLM, 先算确定性信号, 供克劳德参考)"""
    flags: list[str] = []
    odds = pred.get("odds") or {}
    model = pred.get("model") or {}
    bayes = pred.get("bayesian") or {}
    m_dir = model_direction(model)
    b_dir = bayes_direction(bayes)
    mkt = market_direction(odds)
    cold = pred.get("cold_start", False)
    value = pred.get("value") or {}

    # P0 候选: 模型/贝叶斯方向 与 市场方向 全反向 (方向信市场)
    if mkt in ("home", "away") and m_dir in ("home", "away") and m_dir != mkt:
        # 只有市场赔率明显一边倒 (<=1.8) 才判强反向
        fav = odds.get(mkt, 0)
        if fav and fav <= 1.8:
            flags.append(f"P0候选: 模型方向({m_dir})与市场方向({mkt}@{fav:.2f})反向")
    if mkt in ("home", "away") and b_dir in ("home", "away") and b_dir != mkt and m_dir == b_dir:
        fav = odds.get(mkt, 0)
        if fav and fav <= 1.8:
            flags.append(f"P0候选: 模型+贝叶斯同向({b_dir})均与市场({mkt}@{fav:.2f})反向")

    # 冷启动提示
    if cold:
        flags.append("冷启动: 模型参数来自联赛均值, 方向仅市场定价, 不下注")
    else:
        # 无赔率却非冷启动 = 可疑
        if not odds.get("home"):
            flags.append("P1候选: 非冷启动但无赔率, 数据口径可疑")

    # edge / kelly 提示
    best = value.get("best_direction", "none")
    kelly = value.get("kelly", 0) or 0
    if best != "none":
        flags.append(f"sky看好: {best} (Kelly {kelly:.2%})")

    return flags


def _model_over(pred: dict, line: float) -> float:
    """模型在该盘口线的 over 概率: 优先用进球分布, 回退 over_25/over_35"""
    gd = (pred.get("model") or {}).get("goals_distribution") or {}
    if gd:
        def _i(k):
            return 7 if k == "7+" else int(k)
        return sum(p for k, p in gd.items() if _i(k) > line)
    m = pred.get("model") or {}
    if line <= 2.5:
        return m.get("over_25", 0)
    if line <= 3.5:
        return m.get("over_35", 0)
    return 0.0


def build_cross_prompt(pred: dict, note: str, flags: list[str]) -> str:
    home = pred.get("home_team", "?")
    away = pred.get("away_team", "?")
    league = LEAGUE_NAMES.get(pred.get("league_code", ""), pred.get("league_code", ""))
    odds = pred.get("odds") or {}
    model = pred.get("model") or {}
    bayes = pred.get("bayesian") or {}
    value = pred.get("value") or {}
    cold = pred.get("cold_start", False)

    odds_str = ""
    if odds.get("home"):
        odds_str = f"欧赔: 主{odds['home']:.2f}/平{odds['draw']:.2f}/客{odds['away']:.2f}"

    lines = [
        f"=== {home} vs {away} ({league}) ===",
        odds_str,
        f"模型概率: 主{model.get('home_win', 0):.1%} 平{model.get('draw', 0):.1%} 客{model.get('away_win', 0):.1%}",
    ]
    post = (bayes or {}).get("posterior")
    if post:
        lines.append(f"贝叶斯后验: 主{post.get('home', 0):.1%} 平{post.get('draw', 0):.1%} 客{post.get('away', 0):.1%}")
    # 外围大小球实际盘口 (SofaScore 动态线), 模型在该线的 over 概率 (不写死 2.5)
    _ou_line = pred.get("ou_line")
    _btts = model.get("btts", 0)
    if _ou_line is not None:
        _o = pred.get("over_odds")
        _u = pred.get("under_odds")
        _mo = _model_over(pred, _ou_line)
        _ou_txt = f"大小球: 线{_ou_line:g} 大@{_o}/小@{_u} (模型大{_mo:.1%}) | BTTS {_btts:.1%}"
    else:
        _ou_txt = f"大小球: 大2.5 {model.get('over_25', 0):.1%} | 大3.5 {model.get('over_35', 0):.1%} | BTTS {_btts:.1%}"
    lines.append(_ou_txt)
    top5 = model.get("top_5_scores", [])
    if top5:
        lines.append("最可能比分: " + ", ".join(f"{s[0]}({s[1]:.1%})" for s in top5[:3]))
    lines.append(f"冷启动: {'是' if cold else '否'}")
    if value:
        edges = {d: value.get(f"{d}_edge", 0) or 0 for d in ["home", "draw", "away"]}
        lines.append("edge: " + " ".join(f"{d}={edges[d]:+.1%}" for d in ["home", "draw", "away"]))
        lines.append(f"sky看好: {value.get('best_direction', 'none')} (Kelly {value.get('kelly', 0) or 0:.2%})")
    if flags:
        lines.append("结构化预检信号: " + " | ".join(flags))
    if note:
        lines.append("\n=== sky4.0 八维分析笔记 ===")
        lines.append(note[:1500])

    head = ("你是独立定性交叉分析师「克劳德」。sky4.0 已给出量化预测, 你要独立审计它, 不要因为出自同类模型就默认正确。\n\n"
            "审计要点:\n"
            "① 反向错误(P0): sky 方向与市场方向是否全反向? 方向信市场, 结构信模型, 交叉地带谁都不信则跳过。\n"
            "② 冷启动失真(P1): 冷启动标记与模型实际数据是否矛盾? 欧冠/升班马跨级先验要降权。\n"
            "③ 大小球分歧(P2): 大小球方向与最可能比分是否自洽? 与 sky 判断是否分歧? 大小球线必须用证据里的实际线(如线3.5/4.5), 禁止默认2.5。\n"
            "④ 三向冲突: 概率最高方向 / 最可能比分 / 凯利推荐 三方不一致时标结论不可用。\n\n"
            "只输出一个合法 JSON 对象(不要代码块标记、不要概率数字、不要投注建议):\n"
            '{"判定":"同意|保留|反对", "方向":"主胜|主不败|平局|客不败|客胜|跳过", '
            '"置信度":"高|中|低", "问题等级":"P0|P1|P2|无", "首选比分":"如2-1", '
            '"大小球":"大或小+实际盘口线(必须用证据里的线, 如大3.5/小4.5)或跳过", "理由":"一句话", "交叉要点":"分歧或共识说明"}\n\n')

    return head + "\n".join(lines) + "\n\n克劳德审计输出:"


def query_claude(prompt: str, api_key: str | None = None, model: str | None = None) -> str | None:
    """克劳德独立审计: DeepSeek 优先, Anthropic 回退"""
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
        from config import ANTHROPIC_API_KEY as ANTHRO_KEY
    except Exception:
        DEEPSEEK_API_KEY, DEEPSEEK_MODEL, ANTHRO_KEY = "", "deepseek-v4-pro", ""

    ds_key = api_key or DEEPSEEK_API_KEY
    if ds_key:
        r = _try_deepseek(prompt, ds_key, model or DEEPSEEK_MODEL)
        if r:
            return r
        print("  [克劳德] DeepSeek 失败, 回退 Anthropic...")

    if not ANTHRO_KEY:
        return None
    return _try_anthropic(prompt, ANTHRO_KEY, model or "claude-haiku-4-5-20251001")


def _try_deepseek(prompt: str, api_key: str, model: str) -> str | None:
    try:
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("ALL_PROXY", None)
        from deepseek_harness import DeepSeekHarness
        client = DeepSeekHarness(api_key=api_key, disable_thinking_by_default=True)
        resp = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": "你是独立定性交叉分析师「克劳德」。只输出一个合法JSON对象, 中文, 不编造, 不投注。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.4,
        )
        text = (resp.get("message") or {}).get("content") or ""
        return text.strip() if text else None
    except Exception as e:
        print(f"  [克劳德] DeepSeek harness 失败: {e}")
        return None


def _try_anthropic(prompt: str, api_key: str, model: str) -> str | None:
    try:
        import urllib.request
        url = "https://api.anthropic.com/v1/messages"
        body = json.dumps({
            "model": model, "max_tokens": 600, "temperature": 0.4,
            "system": "你是独立定性交叉分析师「克劳德」。只输出一个合法JSON对象, 中文。",
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  [克劳德] Anthropic 失败: {e}")
        return None


def parse_verdict(text: str | None, pred: dict) -> dict | None:
    """把克劳德输出解析为结构化 verdict; 失败时用结构化信号兜底"""
    base = {
        "home": pred.get("home_team", "?"),
        "away": pred.get("away_team", "?"),
        "league": pred.get("league_code", ""),
    }
    if text:
        t = text.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        s = t.find("{")
        e = t.rfind("}")
        if s >= 0 and e > s:
            try:
                obj = json.loads(t[s:e + 1])
                if isinstance(obj, dict):
                    base.update(obj)
                    return base
            except Exception:
                pass
    # 兜底: 只用结构化信号, 不编造方向
    base["判定"] = "保留"
    base["方向"] = "跳过"
    base["置信度"] = "低"
    base["问题等级"] = "无"
    base["首选比分"] = ""
    base["大小球"] = "跳过"
    base["理由"] = "[克劳德LLM不可用, 结构化兜底]"
    base["交叉要点"] = ""
    return base


def cross_check_matches(predictions: list[dict], notes: dict[str, str],
                        use_llm: bool = True, delay: float = 0.3) -> list[dict]:
    """对每场(五大联赛+欧冠)执行克劳德独立交叉, 返回 verdict 列表"""
    verdicts: list[dict] = []
    for i, pred in enumerate(predictions):
        code = pred.get("league_code", "")
        if code not in FOCUS_CODES:
            continue
        home = pred.get("home_team", "?")
        away = pred.get("away_team", "?")
        key = f"{home} vs {away}"
        flags = structural_flags(pred)
        note = notes.get(key, "")

        verdict: dict | None = None
        if use_llm:
            print(f"  [{len(verdicts) + 1}] {key} ({LEAGUE_NAMES.get(code, code)}): 克劳德交叉中...")
            prompt = build_cross_prompt(pred, note, flags)
            verdict = parse_verdict(query_claude(prompt), pred)
            if i < len(predictions) - 1:
                time.sleep(delay)
        else:
            verdict = parse_verdict(None, pred)

        if verdict:
            verdict["structural_flags"] = flags
            # 记录 sky4.0 的方向 + 大小球, 供合并时区分「方向分歧」vs「大小球分歧」
            verdict["sky_direction"] = pick_direction(pred)            # home/away/draw
            # sky 大小球方向: 模型在该盘口线的 over 概率 (大>50% / 小<50%), 而非 edge 信号
            _ln = pred.get("ou_line") or 2.5
            _mo = _model_over(pred, _ln)
            verdict["sky_ou"] = "大" if _mo > 0.5 else ("小" if _mo < 0.5 else None)
            verdicts.append(verdict)
            print(f"    -> {verdict.get('判定')} / {verdict.get('方向')} / {verdict.get('问题等级')}")
    return verdicts


def load_inputs(date_str: str) -> tuple[list[dict], dict[str, str]]:
    out_dir = SKY_DIR / "data" / "output"
    pred_path = out_dir / f"predictions_{date_str}.json"
    note_path = out_dir / f"analysis_notes_final_{date_str}.json"
    predictions = json.loads(pred_path.read_text(encoding="utf-8")) if pred_path.exists() else []
    predictions = dedupe_predictions(predictions)
    notes = json.loads(note_path.read_text(encoding="utf-8")) if note_path.exists() else {}
    return predictions, notes


def main() -> None:
    _fix_stdout()
    import argparse
    ap = argparse.ArgumentParser(description="克劳德独立交叉核验")
    ap.add_argument("date", help="日期 YYYY-MM-DD")
    ap.add_argument("--no-llm", action="store_true", help="只跑结构化预检, 不调 LLM")
    ap.add_argument("--include-elc", action="store_true", help="纳入英冠")
    ap.add_argument("--sky-dir", default=None, help="活量化系统目录 (如 D:\\足球大模型1.0), 读 config+输入")
    ap.add_argument("--out", default=None, help="claude_cross JSON 输出路径")
    args = ap.parse_args()

    if args.sky_dir:
        set_sky_dir(args.sky_dir)
    if args.include_elc:
        FOCUS_CODES.add("ELC")

    predictions, notes = load_inputs(args.date)
    if not predictions:
        print(f"[克劳德] 未找到 {args.date} 的 sky 预测, 终止")
        sys.exit(1)

    verdicts = cross_check_matches(predictions, notes, use_llm=not args.no_llm)
    out_path = Path(args.out) if args.out else (SKY_DIR / "data" / "output" / f"claude_cross_{args.date}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[克劳德] 已写 {out_path} ({len(verdicts)} 场)")


if __name__ == "__main__":
    main()
