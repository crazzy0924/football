# -*- coding: utf-8 -*-
"""把今晚的判断出成一页 —— 工作流的最后一步。

读 `octa_<日期>.json` (八维盲判, 主输出) + `predictions_nl_<日期>.json` (DC+市场融合, 参考轨),
生成 `data/national/预测_<日期>.html`。

纪律: 全中文; 不出投注建议; 反向场次单独标注; 数据缺项如实写「未获取」。
用法: python national/make_page.py [--date 2026-09-24]
"""
import argparse, glob, html, json, os, sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

CSS = """
body{font-family:"Microsoft YaHei",system-ui,sans-serif;background:#f5f6f8;color:#1c1f23;margin:0;padding:24px;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}.sub{color:#666;font-size:13px;margin-bottom:18px}
.card{background:#fff;border-radius:10px;padding:18px 20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #eee;padding-bottom:10px;margin-bottom:12px}
.mt{font-size:18px;font-weight:700}.tm{color:#888;font-size:13px}
.call{font-size:26px;font-weight:800;color:#0b6b3a}
.call.rev{color:#b3261e}
.row{display:flex;gap:22px;flex-wrap:wrap;margin:10px 0;font-size:14px}
.k{color:#888}.v{font-weight:600}
.shape{background:#f0f4ff;border-left:3px solid #3b6fd4;padding:8px 12px;border-radius:4px;margin:10px 0;font-size:14px}
.intel{background:#fffbf0;border-left:3px solid #d4a13b;padding:8px 12px;border-radius:4px;margin:10px 0;font-size:13px}
.div{background:#fdf0ef;border-left:3px solid #b3261e;padding:8px 12px;border-radius:4px;margin:10px 0;font-size:13px}
.risk{color:#8a5a00;font-size:13px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #f0f0f0}
th{color:#888;font-weight:500}
.dim{font-size:12.5px;color:#444}
.foot{color:#777;font-size:12.5px;background:#fff;border-radius:10px;padding:16px 20px}
.tag{display:inline-block;background:#eef1f5;border-radius:4px;padding:1px 7px;font-size:12px;color:#555;margin-right:6px}
.rev-tag{background:#fde8e6;color:#b3261e}
"""


# 球员/教练名中文化 (中文媒体的通行译名)。分析师拿英文名做分析, 页面要能直接读。
NAME_MAP = {
    "Haaland": "哈兰德", "Ødegaard": "厄德高", "Odegaard": "厄德高",
    "Sørloth": "索尔洛特", "Sorloth": "索尔洛特", "Botheim": "博特海姆",
    "Solbakken": "索尔巴肯", "Riemer": "里默", "Højlund": "霍伊伦", "Hojlund": "霍伊伦",
    "Eriksen": "埃里克森", "Schjelderup": "谢尔德鲁普", "Nusa": "努萨", "Bobb": "鲍勃",
    "Mancini": "曼奇尼", "Spalletti": "斯帕莱蒂", "Esposito": "埃斯波西托", "Romano": "罗马诺",
    "Retegui": "雷特吉", "Rovella": "罗韦拉", "Tzolis": "佐利斯", "Karetsas": "卡雷察斯",
    "Tadic": "塔迪奇", "Montella": "蒙特拉", "Klopp": "克洛普", "Xavi": "哈维",
    "Pio": "皮奥", "UEFA": "欧足联",
    # 注意: 不要写空字符串映射 (如 "League": "") —— 那会把正常文案也删掉。
    # 2026-09-24 实际踩到: 标题被削成 "欧国联  A 判断"。文案该改文案本身。
}


def localize(text: str) -> str:
    """把英文队名与已知球员名换成中文。返回 (文本, 未译的拉丁词列表)。"""
    import re as _re
    from national import EN_TO_CN
    out = text
    # ⚠️ 不能用 \b: Python 的 re 在 Unicode 下把中文也算"词字符", 所以
    #   "意大利Italy" 这种中文紧挨英文的地方 \b 匹配不上, 替换会**静默失败**
    #   (2026-09-24 实际踩到: 页面上残留 Belgium / Italy)。
    #   改用"两侧不是拉丁字母"判定。
    def _sub(src, mapping):
        for en, cn in mapping.items():
            src = _re.sub(r"(?<![A-Za-z])" + _re.escape(en) + r"(?![A-Za-z])", cn, src)
        return src
    out = _sub(out, EN_TO_CN)
    out = _sub(out, NAME_MAP)
    # 剩下的拉丁词 (排除 HTML/CSS 关键字) 报出来, 便于继续补译名
    SKIP = {"html", "lang", "head", "meta", "charset", "viewport", "title", "style", "body",
            "class", "div", "table", "tr", "td", "th", "DOCTYPE", "Microsoft", "YaHei", "UTF"}
    # 只扫**可见文本**: 先去掉 style/script, 再去掉所有标签 —— 否则 CSS 类名会淹没警告
    body = _re.sub(r"<(style|script)[\s\S]*?</\1>", " ", out)
    body = _re.sub(r"<[^>]+>", " ", body)
    left = sorted({w for w in _re.findall(r"[A-Za-z][A-Za-z\-\.]{2,}", body)
                   if w not in SKIP and not w.startswith("rgba")})
    return out, left


def esc(x):
    return html.escape(str(x if x is not None else ""))


def kf(v):
    return "未获取" if not v or str(v).strip().lower() in ("none", "无") else esc(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    args = ap.parse_args()
    d = os.path.join(_ROOT, "data", "national")
    octa_files = ([os.path.join(d, "octa_%s.json" % args.date)] if args.date
                  else sorted(glob.glob(os.path.join(d, "octa_*.json"))))
    if not octa_files or not os.path.exists(octa_files[-1]):
        print("没找到 octa_*.json, 先跑 national/octa.py")
        return 1
    f = octa_files[-1]
    date_str = os.path.basename(f)[5:-5]
    recs = json.load(open(f, encoding="utf-8"))
    # DC 参考轨
    ref = {}
    pf = os.path.join(d, "predictions_nl_%s.json" % date_str)
    if os.path.exists(pf):
        for m in json.load(open(pf, encoding="utf-8")).get("matches", []):
            ref[(m.get("home"), m.get("away"))] = m
    recs.sort(key=lambda r: str(r.get("kickoff_abs") or ""))

    P = []
    P.append("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    P.append("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    P.append("<title>欧国联 A 级 判断 · %s</title><style>%s</style></head><body><div class=\"wrap\">" % (date_str, CSS))
    P.append("<h1>欧国联 A 级 · 第一轮</h1>")
    P.append("<div class=\"sub\">判断时间 %s · %d 场 · 先遮赔率独立判断，再揭示赔率对照</div>"
             % (esc(recs[0].get("ts")), len(recs)))

    for r in recs:
        s1 = r.get("stage1_blind") or {}
        s2 = r.get("stage2_vs_market") or {}
        fin = r.get("final") or {}
        mp = r.get("market_probs") or {}
        odds = r.get("odds") or {}
        rev = (s2.get("市场与我的关系") == "反向")
        P.append("<div class=\"card\">")
        P.append("<div class=\"hd\"><div><span class=\"mt\">%s vs %s</span>"
                 % (esc(r.get("home_cn")), esc(r.get("away_cn"))))
        P.append(" <span class=\"tm\">%s · %s 开球</span></div>"
                 % (esc(r.get("num")), esc(r.get("kickoff_abs"))))
        P.append("<div class=\"call%s\">%s %s</div></div>"
                 % (" rev" if rev else "", esc(fin.get("站边")), esc(fin.get("比分"))))
        P.append("<div class=\"row\">")
        P.append("<div><span class=\"k\">置信度</span> <span class=\"v\">%s</span></div>" % esc(fin.get("置信度分")))
        P.append("<div><span class=\"k\">自洽度</span> <span class=\"v\">%s</span></div>" % esc(fin.get("自洽度")))
        P.append("<div><span class=\"k\">方向分</span> <span class=\"v\">%s</span></div>" % esc(fin.get("方向分")))
        P.append("<div><span class=\"k\">与市场</span> <span class=\"v\">%s</span></div>" % esc(s2.get("市场与我的关系")))
        if odds.get("h"):
            P.append("<div><span class=\"k\">体彩</span> <span class=\"v\">%.2f / %.2f / %.2f</span></div>"
                     % (odds.get("h", 0), odds.get("d", 0), odds.get("a", 0)))
        if mp:
            P.append("<div><span class=\"k\">市场去水</span> <span class=\"v\">%.0f%% / %.0f%% / %.0f%%</span></div>"
                     % (mp.get("home", 0) * 100, mp.get("draw", 0) * 100, mp.get("away", 0) * 100))
        P.append("</div>")
        if s1.get("这场的形状"):
            P.append("<div class=\"shape\">%s</div>" % esc(s1.get("这场的形状")))
        # 情报维度原文
        for dim in (s1.get("七维") or []):
            if dim.get("维度") in ("阵容伤停", "战意轮换"):
                P.append("<div class=\"intel\"><b>%s</b> · %s</div>"
                         % (esc(dim.get("维度")), kf(dim.get("证据"))))
        if rev and s2.get("分歧说明"):
            P.append("<div class=\"div\"><b>分歧说明</b> · %s</div>" % esc(s2.get("分歧说明")))
        if s1.get("最大风险"):
            P.append("<div class=\"risk\">最大风险: %s</div>" % esc(s1.get("最大风险")))
        # 路径
        path = s1.get("路径") or {}
        if path:
            P.append("<table><tr><th>路径</th><th>触发条件</th><th>比分</th></tr>")
            for name in ("常规", "平局", "冷门"):
                p = path.get(name) or {}
                if p:
                    P.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (esc(name), esc(p.get("触发")), esc("、".join(p.get("比分") or []))))
            P.append("</table>")
        # 七维明细
        P.append("<table><tr><th>维度</th><th>优势分</th><th>权重</th><th>证据</th></tr>")
        for dim in (s1.get("七维") or []):
            P.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class=\"dim\">%s</td></tr>"
                     % (esc(dim.get("维度")), esc(dim.get("优势分")), esc(dim.get("权重")), kf(dim.get("证据"))))
        P.append("</table>")
        # 参考轨
        rf = ref.get((r.get("home"), r.get("away")))
        if rf and rf.get("fused"):
            fz = rf["fused"]
            P.append("<div class=\"tm\" style=\"margin-top:10px\">参考轨 (纯数据 DC + 市场融合 w=0.10): "
                     "主 %.0f%% / 平 %.0f%% / 客 %.0f%%</div>"
                     % (fz.get("home", 0) * 100, fz.get("draw", 0) * 100, fz.get("away", 0) * 100))
        if s2.get("反向验证"):
            P.append("<div class=\"tm\" style=\"margin-top:6px\">反向验证: %s</div>" % esc(s2.get("反向验证")))
        P.append("</div>")

    P.append("<div class=\"foot\">")
    P.append("<b>纪律</b><br>")
    P.append("· 本页是**判断**, 不是投注建议。俱乐部侧已实测: 下注信号是反向指标。<br>")
    P.append("· 第一段**遮住赔率**独立判断; 第二段才揭示赔率, 只有「市场揭示了我确实漏掉的具体事实」才允许改判。<br>")
    P.append("· 标注「反向」的场次 = 我们与市场相反。**只有这些场次计入判据**(同向只是在附和市场)。<br>")
    P.append("· 自洽度 = 同一份证据跑 3 次取多数的一致程度。<b>2/3 表示这个判断本身不稳定, 要打折看。</b><br>")
    P.append("· ⚠️ 这套方法**无法回测**(情报是当天抓的), 且 League A 每年只新增 48 场 —— "
             "<b>显著性永远拿不到, 单轮数字不许当结论。</b><br>")
    P.append("· 情报由主代理 web_search 抓取, 每条带来源; 抓不到的如实写「未获取」, 权重记 0, 禁止编造。")
    P.append("</div></div></body></html>")

    page, left = localize("\n".join(P))
    out = os.path.join(d, "预测_%s.html" % date_str)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("已生成 -> %s" % os.path.relpath(out, _ROOT))
    if left:
        print("   ⚠ 页面里还有未译的拉丁词 (补 NAME_MAP 即可): %s" % ", ".join(left[:20]))
    print("  %d 场; 反向 %d 场" % (len(recs), sum(1 for r in recs if (r.get("stage2_vs_market") or {}).get("市场与我的关系") == "反向")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())