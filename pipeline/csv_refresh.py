# -*- coding: utf-8 -*-
"""
新赛季 CSV 刷新 (2026-08-20 新增)

每周重训前自动从 football-data.co.uk 下载最新赛季五大联赛 CSV:
  E0=英超 SP1=西甲 D1=德甲 I1=意甲 F1=法甲
保存为 data/historical_odds/{div}_2026_2027.csv (loader 自动发现)。

此前训练数据停在 2025-26 赛季, 升班马永远无参数 → 永远冷启动。
新赛季比赛随 CSV 每周进场, 重训后升班马逐渐获得真实参数, 冷启动逐轮解除。

用法: python pipeline/csv_refresh.py
"""
from __future__ import annotations

import io
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 五大联赛 football-data.co.uk 代码 + 当前赛季目录
FOCUS_DIVS = {"E0": "英超", "SP1": "西甲", "D1": "德甲", "I1": "意甲", "F1": "法甲"}
BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
CURRENT_SEASON = "2627"


def _download(div: str) -> tuple[bool, int]:
    """下载单个联赛 CSV, 返回 (成功, 行数)"""
    import urllib.request
    import urllib.error
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = BASE_URL.format(season=CURRENT_SEASON, div=div)
    out_path = os.path.join("data", "historical_odds", f"{div}_2026_2027.csv")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (300, 404):
            print(f"[CSV] {div} 文件尚未生成 (联赛未开赛), 下周一自动再试")
        else:
            print(f"[CSV] {div} 下载失败: HTTP {e.code}")
        return False, 0
    except Exception as e:
        print(f"[CSV] {div} 下载失败: {e}")
        return False, 0
    # 校验: 有表头且(有比赛数据 或 文件暂空但合法)
    if "Date" not in raw.splitlines()[0] if raw.splitlines() else True:
        print(f"[CSV] {div} 内容异常, 跳过")
        return False, 0
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(raw.replace("\r\n", "\n").replace("\r", "\n"))
    return True, max(0, len(lines) - 1)


def main() -> None:
    total_rows = 0
    for div, name in FOCUS_DIVS.items():
        ok, rows = _download(div)
        if ok:
            total_rows += rows
            print(f"[CSV] {name}({div}) 2026-27: {rows} 场")
    print(f"[CSV] 本次共 {total_rows} 场新赛季比赛进入训练库 (周一重训自动生效)")


if __name__ == "__main__":
    main()
