# -*- coding: utf-8 -*-
"""刷新国家队语料 —— 上游 martj42/international_results。

为什么需要它 (2026-09-24):
  我们本地语料停在 2026-08-26。核实过: 那不是"滞后", 而是 8/26 之后本来就没有国际比赛
  (欧国联 9/24 才开打)。所以回灌 = **每次出预测之前重下上游**。

上游确实有 1-2 天延迟。万一某轮打完上游还没更新, 用 data/national/results_local.csv 补录
(schema 与上游完全一致), corpus.load_matches 会自动并进来, 不会被卡住。

用法:
    python national/refresh_corpus.py            # 下载并替换 (有变化时)
    python national/refresh_corpus.py --check    # 只看差异, 不写
"""
import argparse, csv, io, json, os, shutil, sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DST = os.path.join(_ROOT, "data", "national", "results.csv")
META = os.path.join(_ROOT, "data", "national", "corpus_meta.json")


def _rows(text: str):
    return list(csv.DictReader(io.StringIO(text)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只看差异, 不写文件")
    args = ap.parse_args()

    import requests
    print("下载上游: %s" % URL)
    r = requests.get(URL, timeout=120)
    r.raise_for_status()
    up = _rows(r.content.decode("utf-8"))
    up_last = max(x["date"] for x in up)
    print("  上游 %d 行, 最新 %s" % (len(up), up_last))

    old = _rows(open(DST, encoding="utf-8").read()) if os.path.exists(DST) else []
    old_last = max((x["date"] for x in old), default="")
    print("  本地 %d 行, 最新 %s" % (len(old), old_last or "(无)"))

    if old and len(up) < len(old):
        print("  ⚠ 上游行数变少了 (%d -> %d), 疑似上游回退。**拒绝覆盖**, 请人工确认。"
              % (len(old), len(up)))
        return 1

    if up_last <= old_last and len(up) == len(old):
        print("  => 无变化, 不需要刷新")
        return 0

    new = [x for x in up if x["date"] > old_last]
    print("  => 新增 %d 场 (本地最新之后)" % len(new))
    if new:
        import collections
        for k, v in collections.Counter(x["tournament"] for x in new).most_common(10):
            print("       %-44s %d" % (k[:44], v))
        nl = [x for x in new if x["tournament"].startswith("UEFA Nations League")]
        for x in sorted(nl, key=lambda y: y["date"])[:20]:
            print("       [NL] %s %-18s %s-%s %-18s %s"
                  % (x["date"], x["home_team"], x["home_score"], x["away_score"],
                     x["away_team"], "中" if x["neutral"] == "TRUE" else "主"))

    if args.check:
        print("  [--check] 不写文件")
        return 0

    if os.path.exists(DST):
        shutil.copy(DST, DST + ".bak")
    with open(DST, "w", encoding="utf-8") as fh:
        fh.write(r.content.decode("utf-8"))
    with open(META, "w", encoding="utf-8") as fh:
        json.dump({"downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "rows": len(up), "latest_date": up_last, "source": URL},
                  fh, ensure_ascii=False, indent=2)
    print("  已刷新 -> data/national/results.csv (旧版备份为 .bak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())