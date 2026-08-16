# -*- coding: utf-8 -*-
"""
自动伤停侦察 (Phase 11 · 零注册零订阅方案)

用 cn.bing.com 中文搜索 "{中文队名} 伤停", 提取新闻摘要,
写入 data/intel/YYYY-MM-DD.txt 供 predict --llm 分析师参考。

全部公开通道, 无需任何 API key/订阅。摘要未经人工核实。
用法: python pipeline/injury_recon.py [YYYY-MM-DD]
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 伤停相关关键词 (过滤噪音; 不要裸"缺/停"等常见字)
KEEP_RE = re.compile(r"伤停|伤病|伤缺|缺席|缺阵|无缘|受伤|停赛|禁赛|injur|out of|doubt|susp")
DROP_RE = re.compile(r"字典|汉典|王国|旅游|部首|拼音|康熙|国家|首都|海风|步行导览")


def _search_bing(query: str) -> list[str]:
    """cn.bing.com 搜索 → 摘要列表 (adlt=strict 过滤垃圾)"""
    import httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get("https://cn.bing.com/search", params={"q": query, "adlt": "strict"}, headers=headers)
        if r.status_code != 200:
            return []
        blocks = re.findall(r'<li class="b_algo"[\s\S]*?</li>', r.text)
        out = []
        for b in blocks:
            text = re.sub(r"<[^>]+>", " ", b)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 30:
                continue
            if DROP_RE.search(text):
                continue
            if not KEEP_RE.search(text):
                continue
            out.append(text[:200])
        return out[:4]
    except Exception:
        return []


def _cn_name(team: str) -> str:
    """英文名 → 中文名 (反向查表)"""
    from pipeline.team_names import CN_TO_EN_TEAM
    for cn, en in CN_TO_EN_TEAM.items():
        if en == team:
            return cn
    return team


def build_injury_intel(teams: list[str]) -> str:
    """每队中文搜索伤停, 生成情报文本"""
    lines = ["=== 自动伤停侦察 (Bing搜索摘要, 未经核实, 仅供分析师参考) ==="]
    for team in teams:
        cn = _cn_name(team)
        queries = [f"{cn}队 伤停 2026", f"{cn} 伤停名单 2026", f"{cn} 伤停"]
        got = []
        for q in queries:
            got = _search_bing(q)
            if got:
                break
            time.sleep(3)
        if not got:
            continue
        lines.append(f"[{team} / {cn}]")
        for s in got:
            lines.append(f"  - {s}")
        lines.append("")
        time.sleep(5)  # 限速友好
    return "\n".join(lines).strip()


def main() -> None:
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    today_path = os.path.join("data", "today.json")
    if not os.path.exists(today_path):
        print("未找到 data/today.json, 请先运行 fetch_sporttery.py")
        return
    import json
    with open(today_path, "r", encoding="utf-8") as f:
        matches = json.load(f)
    teams = []
    seen = set()
    for m in matches:
        for t in (m.get("home_team"), m.get("away_team")):
            if t and t not in seen:
                seen.add(t)
                teams.append(t)
    print(f"伤停侦察: {len(teams)} 支球队...")
    intel = build_injury_intel(teams)
    if not intel:
        print("未获取到有效摘要。")
        return

    intel_path = os.path.join("data", "intel", f"{date_str}.txt")
    os.makedirs(os.path.dirname(intel_path), exist_ok=True)
    existing = ""
    if os.path.exists(intel_path):
        with open(intel_path, "r", encoding="utf-8") as f:
            existing = f.read().strip()
    if existing and "自动伤停侦察" not in existing:
        content_out = existing + "\n\n" + intel + "\n"
    else:
        content_out = intel + "\n"
    with open(intel_path, "w", encoding="utf-8") as f:
        f.write(content_out)
    print(f"已写入情报 → {intel_path}")
    print(intel[:600])


if __name__ == "__main__":
    main()
