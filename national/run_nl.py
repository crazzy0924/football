# -*- coding: utf-8 -*-
"""欧国联 League A 预测 —— 生产入口。

用法:
    python national/run_nl.py --date 2026-09-24
    python national/run_nl.py --date 2026-09-24 --dry-run

纪律 (2026-09-24 用户拍板, 与俱乐部链路一致):
  - 只做 League A 16 队; B/C/D 一律排除。
  - **不出下注建议**。俱乐部侧实测已证明下注信号是反向指标 (CLAUDE.md 第九节),
    国家队侧更没有任何 edge 证据, 所以这里只输出概率, 不给任何投注结论。
  - model_confidence 固定很低 (默认 0.20): 我们**没有**任何国家队模型 vs 市场的
    样本外证据, 在拿到证据之前市场必须占主导。吃到 MD1-MD6 的赔率后, 用配对检验
    重新定这个数 (todo: 见 docs/欧国联预测方案.md)。
"""
import argparse, json, os, ssl, sys, urllib.request
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from national import ALL_A_TEAMS, CN_TO_EN, EN_TO_CN, LEAGUE_A_2026_27  # noqa: E402
from national.corpus import load_matches  # noqa: E402
from national.dc_national import NationalDC  # noqa: E402
from national.standings import build_tables, rounds_played, stakes  # noqa: E402

# 模型在市场面前的话语权。
#
# 2026-09-24 定为 0.10 (原 0.20), 依据是欧国联专项回测:
#   目标口径(League A 强强对话, n=102) 上, 模型相对"无技能基准"只改善 1.9%,
#   对 Elo 的配对检验 t=-1.19 不显著。也就是说在这类比赛上我们拿不出"比瞎猜强"的证据。
#   另外实测: 要检出 Brier 差 0.02 需要 933 场, 而我们每年只能新增 48 场。
#   => 这个数不可能被数据"调优", 只能是基于先验的保守选择。0.10 = 市场绝对主导。
NL_MODEL_CONFIDENCE = 0.10

# 分歧预警阈值 (百分点)。方案A下模型的定位是"诊断"而非"预测":
# 它的价值在于**发现市场与模型的重大分歧**, 提示"市场可能看漏了什么"或"我们可能算错了"。
# 注意: 这是诊断信号, 不是投注信号 —— 俱乐部侧已实测下注信号是反向指标 (CLAUDE.md 第九节)。
DIVERGENCE_ALERT = 8.0

# 超参在**目标口径**(欧足联内部 + 正式比赛)上调出来的, 不是在"全部国际比赛"上。
# 2026-09-24 教训: 一开始调在全部国际比赛上 -> 选出半衰期 1095 天, 结果把挪威这种
# "近两年才崛起"的队评低了 (挪威 hl=365 时排 #14, hl=1095 时掉到 #18)。
# 目标口径验证 Brier: hl=730 -> 0.4405 (最优, 次优 547 天 0.4410, 最差 180 天 0.4630)。
ALPHA_TEAM = 0.2
HALF_LIFE_DAYS = 730.0

GROUP_OF = {t: g for g, ts in LEAGUE_A_2026_27.items() for t in ts}


def fetch_sporttery() -> list[dict]:
    """拉体彩在售场次 (含 HAD/HHAD 赔率)。只取需要的字段。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPSHandler(context=ctx))
    hdr = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sporttery.cn/"}
    out: dict[str, dict] = {}
    for pool in ["HAD", "HHAD"]:
        url = ("https://webapi.sporttery.cn/gateway/uniform/football/"
               "getMatchCalculatorV1.qry?poolCode=%s&channelId=500" % pool)
        req = urllib.request.Request(url, headers=hdr)
        data = json.loads(op.open(req, timeout=25).read().decode("utf-8"))
        for blk in data["value"]["matchInfoList"]:
            for m in blk.get("subMatchList", []):
                mid = m["matchId"]
                if mid not in out:
                    out[mid] = {
                        "match_id": mid,
                        "num": m.get("matchNumStr", ""),
                        "league": m.get("leagueName") or m.get("leagueAbbName") or "",
                        "home_cn": m.get("homeTeamAllName", ""),
                        "away_cn": m.get("awayTeamAllName", ""),
                        "business_date": m.get("businessDate", ""),
                        "match_time": (m.get("matchTime") or "").strip(),
                    }
                out[mid][pool.lower()] = m.get(pool.lower(), {})
    return list(out.values())


def kickoff_abs(business_date: str, match_time: str):
    """体彩比赛日 + 开球时间 -> 绝对开球时间。

    铁律: kickoff < 12:00 视为次日凌晨, 要 +1 天。
    """
    try:
        parts = [int(x) for x in match_time.split(":")]
        hh, mm = parts[0], parts[1]
        d = datetime.strptime(business_date, "%Y-%m-%d")
        if hh < 12:
            d += timedelta(days=1)
        return d.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None


ODDS_LOG = os.path.join(_ROOT, "data", "national", "odds_log.jsonl")


def _append_odds_log(results: list, generated_at: str) -> None:
    """追加一行一条赔率观测。jsonl 便于后续按 match 聚合看赔率变动。"""
    os.makedirs(os.path.dirname(ODDS_LOG), exist_ok=True)
    n = 0
    with open(ODDS_LOG, "a", encoding="utf-8") as fh:
        for l in results:
            if not l.get("market"):
                continue
            fh.write(json.dumps({
                "ts": generated_at,
                "business_date": l["business_date"],
                "num": l["num"], "group": l["group"],
                "home": l["home"], "away": l["away"],
                "kickoff_abs": l["kickoff_abs"],
                "odds": l["odds"],
                "market": l["market"],
                "model": {k: l["model"][k] for k in ("home", "draw", "away")},
                "fused": l["fused"],
                "model_weight": l["model_weight"],
                "divergence": l.get("divergence"),
            }, ensure_ascii=False) + "\n")
            n += 1
    if n:
        print("赔率存档 +%d 行 -> %s" % (n, os.path.relpath(ODDS_LOG, _ROOT)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mc", type=float, default=NL_MODEL_CONFIDENCE)
    ap.add_argument("--refresh", action="store_true",
                    help="出预测前先刷新语料 (重下上游)。上游有 1-2 天延迟, 建议每轮都加。")
    args = ap.parse_args()

    now = datetime.now()
    print("=" * 78)
    print("欧国联 League A 预测   business_date=%s   (本机 %s)"
          % (args.date, now.strftime("%Y-%m-%d %H:%M")))
    print("=" * 78)

    # ── 0. 刷新语料 (可选) ──
    if args.refresh:
        print("刷新语料 ...")
        try:
            import subprocess
            subprocess.run([sys.executable, os.path.join(_ROOT, "national", "refresh_corpus.py")],
                           cwd=_ROOT, check=False)
        except Exception as e:
            print("  刷新失败 (%s), 继续用现有语料" % type(e).__name__)
        print()

    # ── 1. 拟合 ──
    ms = load_matches(since="2016-01-01")
    model = NationalDC(half_life_days=HALF_LIFE_DAYS, alpha_team=ALPHA_TEAM).fit(ms)
    print("语料 %d 场 (%s -> %s)   球队 %d 支   拟合 %s"
          % (len(ms), ms[0]["date"], ms[-1]["date"], len(model.teams),
             "OK" if model.fit_info["success"] else "未收敛"))
    # 小组形势 —— **纯展示层, 不进模型** (见 national/standings.py 文件头与方案文档 9.2)
    _tables = build_tables(ms)
    _stakes = {g: stakes(tb) for g, tb in _tables.items()}
    _rnd = max((rounds_played(t) for t in _tables.values()), default=0)
    print("小组形势: 已完成 %d/%d 轮 (仅展示, 不影响模型)" % (_rnd, 6))

    # ── 2. 取体彩在售场次, 过滤到 League A ──
    raw = fetch_sporttery()
    picks = []
    for m in raw:
        if "欧国联" not in (m["league"] or ""):
            continue
        h = CN_TO_EN.get(m["home_cn"].strip())
        a = CN_TO_EN.get(m["away_cn"].strip())
        if not h or not a:
            m["_skip"] = "不在 League A 名单(多半是 B/C/D 级)"
            picks.append(m)
            continue
        m["home"], m["away"] = h, a
        picks.append(m)

    inscope = [m for m in picks if m.get("home")]
    skipped = [m for m in picks if not m.get("home")]
    # 已开赛的不预测 (与俱乐部侧同一条纪律: 预测入口跳过已开赛场次)
    live = [m for m in inscope
            if not (kickoff_abs(m["business_date"], m["match_time"]) or datetime.max) < now]
    nstarted = len(inscope) - len(live)
    print("体彩在售欧国联 %d 场 -> 命中 League A %d 场, 排除 %d 场, 已开赛跳过 %d 场"
          % (len(picks), len(inscope), len(skipped), nstarted))
    for m in skipped:
        print("   排除: %s vs %s  (%s)" % (m["home_cn"], m["away_cn"], m["_skip"]))
    if live:
        bds = sorted({m["business_date"] for m in live})
        print("   覆盖体彩比赛日: %s   共 %d 场 (含非当日挂出的场次)" % (", ".join(bds), len(live)))
        print("   注意: --date 只决定输出文件名; 预测范围是**全部未开赛的 League A 场次**。")
    inscope = live
    print()

    # ── 3. 逐场预测 ──
    results = []
    for m in sorted(inscope, key=lambda x: x["match_time"]):
        h, a = m["home"], m["away"]
        ko = kickoff_abs(m["business_date"], m["match_time"])
        started = ko is not None and ko < now
        dc = model.predict(h, a, neutral=False, comp="NL")
        had = m.get("had") or {}
        try:
            oh, od, oa = float(had["h"]), float(had["d"]), float(had["a"])
        except Exception:
            oh = od = oa = 0.0

        line = {
            "num": m["num"], "league": m["league"],
            "group": GROUP_OF.get(h, "?"),
            "home": h, "away": a,
            "home_cn": m["home_cn"], "away_cn": m["away_cn"],
            "business_date": m["business_date"], "match_time": m["match_time"],
            "kickoff_abs": ko.strftime("%Y-%m-%d %H:%M") if ko else None,
            "started": bool(started),
            "model": {"home": dc["home_win"], "draw": dc["draw"], "away": dc["away_win"],
                      "lam_h": dc["lam_h"], "lam_a": dc["lam_a"],
                      "over_15": dc["over_15"], "over_25": dc["over_25"],
                      "over_35": dc["over_35"], "btts": dc["btts"],
                      "top_scores": dc["top_scores"][:3]},
            "odds": {"h": oh, "d": od, "a": oa},
        }

        if oh > 1 and od > 1 and oa > 1:
            from models.odds import implied_probability
            from national.fusion import log_opinion_pool
            imp = implied_probability(oh, od, oa)
            mkt = [imp["home"], imp["draw"], imp["away"]]
            fused = log_opinion_pool(
                [dc["home_win"], dc["draw"], dc["away_win"]], mkt, w=args.mc)
            line["market"] = {"home": mkt[0], "draw": mkt[1],
                              "away": mkt[2], "margin": imp["margin"]}
            line["fused"] = {"home": round(fused[0], 4), "draw": round(fused[1], 4),
                             "away": round(fused[2], 4)}
            line["model_weight"] = args.mc
            line["pick"] = ["Home Win", "Draw", "Away Win"][
                max(range(3), key=lambda i: fused[i])]
        else:
            line["market"] = None
            line["fused"] = None
            line["pick"] = None
        results.append(line)

    # ── 4. 打印 ──
    for l in results:
        flag = "  ⚠ 已开赛" if l["started"] else ""
        print("-" * 78)
        print("%s  [%s组]  %s vs %s%s"
              % (l["num"], l["group"], l["home_cn"], l["away_cn"], flag))
        print("    开球 %s (体彩比赛日 %s %s)"
              % (l["kickoff_abs"], l["business_date"], l["match_time"]))
        md = l["model"]
        print("    模型 DC     主 %5.1f%%  平 %5.1f%%  客 %5.1f%%   预期进球 %.2f-%.2f"
              % (md["home"] * 100, md["draw"] * 100, md["away"] * 100, md["lam_h"], md["lam_a"]))
        if l["market"]:
            mk = l["market"]
            print("    市场 去水   主 %5.1f%%  平 %5.1f%%  客 %5.1f%%   (抽水 %.1f%%, 体彩 %.2f/%.2f/%.2f)"
                  % (mk["home"] * 100, mk["draw"] * 100, mk["away"] * 100,
                     mk["margin"] * 100, l["odds"]["h"], l["odds"]["d"], l["odds"]["a"]))
            fu = l["fused"]
            print("    融合后      主 %5.1f%%  平 %5.1f%%  客 %5.1f%%   (模型权重 %.2f, mc=%.2f)"
                  % (fu["home"] * 100, fu["draw"] * 100, fu["away"] * 100,
                     l["model_weight"] or 0, args.mc))
            # 模型与市场的分歧 —— 这是方案A下模型唯一的用途, 只报告, 绝不据此给建议
            dv = [(md[k] - mk[k]) * 100 for k in ("home", "draw", "away")]
            big = max(range(3), key=lambda i: abs(dv[i]))
            nmv = ["主胜", "平局", "客胜"][big]
            line["divergence"] = {"outcome": ["home", "draw", "away"][big],
                                  "pp": round(dv[big], 1),
                                  "alert": abs(dv[big]) >= DIVERGENCE_ALERT}
            # 注意: 这里必须用 l["home"]/l["away"], 不能用 h/a ——
            # 那是上面构造循环的残留变量, 会显示成最后一场的两队 (2026-09-24 踩过)。
            _st = _stakes.get(l["group"], {})
            _nh = _st.get(l["home"], {}).get("note", "-")
            _na = _st.get(l["away"], {}).get("note", "-")
            print("    形势(%d轮)   %s: %s   %s: %s"
                  % (_rnd, l["home_cn"], _nh, l["away_cn"], _na))
            print("    分歧        模型比市场高估「%s」%+.1f 个百分点%s"
                  % (nmv, dv[big], "   ⚠ 触发预警" if abs(dv[big]) >= DIVERGENCE_ALERT else ""))
            if abs(dv[big]) >= DIVERGENCE_ALERT:
                print("                ⚠ 分歧 >= %.0f 个点。这是**诊断**不是投注信号: 要么市场看漏了,"
                      % DIVERGENCE_ALERT)
                print("                  要么我们算错了(见 docs/欧国联预测方案.md 第 9.1 节挪威那场)。")
        else:
            print("    市场        无体彩 SPF 赔率")
        print("    大小球(仅模型, 体彩无此玩法) 大1.5 %5.1f%%  大2.5 %5.1f%%  大3.5 %5.1f%%   BTTS %5.1f%%"
              % (md["over_15"] * 100, md["over_25"] * 100, md["over_35"] * 100, md["btts"] * 100))
        print("    波胆(仅模型) %s" % ", ".join("%s %.1f%%" % (s, p * 100) for s, p in md["top_scores"]))
    print("-" * 78)

    # ── 5. 落盘 ──
    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "business_date": args.date,
        "scope": "UEFA Nations League League A",
        "model": {"name": "NationalDC", "alpha_team": ALPHA_TEAM,
                  "half_life_days": HALF_LIFE_DAYS, "n_matches": len(ms),
                  "n_teams": len(model.teams), "rho": round(model.rho, 4),
                  "home_adv_NL": round(model.ha.get("NL", 0), 4),
                  "fit_success": model.fit_info["success"]},
        "model_confidence": args.mc,
        "warning": ("本模型只在 ELO/基准 上做过样本外验证 (Brier 0.45488 / 66.9% @ 欧足联内部+正式), "
                    "**从未与市场赔率做过配对检验**。模型权重被刻意压低, 以市场为主导。"),
        "matches": results,
    }
    # ── 5b. 赔率存档 (方案A的硬需求: 每轮把观测到的赔率留下, 供将来任何口径的回测用) ──
    _append_odds_log(results, out["generated_at"])

    if args.dry_run:
        print("[dry-run] 不写 predictions 文件")
        return
    dst = os.path.join(_ROOT, "data", "national")
    os.makedirs(dst, exist_ok=True)
    p = os.path.join(dst, "predictions_nl_%s.json" % args.date)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("已保存 -> %s" % os.path.relpath(p, _ROOT))


if __name__ == "__main__":
    main()