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

# 来源域名 → 中文标签 (证据账本: 保留来源可追溯, 且通过汉化纪律)
DOMAIN_CN = [
    ("sporttery.cn", "体彩官网"), ("premierleague.com", "英超官网"), ("laliga.com", "西甲官网"),
    ("sohu.com", "搜狐"), ("sina.com.cn", "新浪"), ("sina.cn", "新浪"), ("qq.com", "腾讯"),
    ("163.com", "网易"), ("toutiao.com", "今日头条"), ("zhihu.com", "知乎"),
    ("dongqiudi.com", "懂球帝"), ("hupu.com", "虎扑"), ("7m.com.cn", "7M体育"), ("7m.hk", "7M体育"),
    ("okooo.com", "澳客"), ("zhibo8", "直播吧"), ("baidu.com", "百度"), ("bilibili.com", "哔哩哔哩"),
    ("ifeng.com", "凤凰网"), ("thepaper.cn", "澎湃"), ("cctv.com", "央视"), ("xinhuanet.com", "新华社"),
    ("people.com.cn", "人民网"), ("news.qq.com", "腾讯"), ("goal.com", "进球网"), ("transfermarkt", "转会市场"),
]


def _cn_source(text: str) -> str:
    """把搜索摘要里的英文域名换成中文来源标签 (保留可追溯)"""
    for dom, label in DOMAIN_CN:
        if dom in text:
            text = re.sub(r"https?://\S+|\b" + re.escape(dom.split('.')[0]) + r"\S*", "", text)
            return "来源:" + label + " " + text.strip()
    text = re.sub(r"https?://\S+", "", text)
    return "来源:网络 " + text.strip()


def _search_bing(query: str, filter_kw: bool = True, require: list[str] | None = None) -> list[str]:
    """cn.bing.com 搜索 → 摘要列表 (adlt=strict 过滤垃圾)

    filter_kw=False 时不按伤停关键词过滤 (用于天气/裁判等侦察)
    require: 结果必须包含这些词 (队名相关性过滤, 防情报错配)
    """
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
            if filter_kw and not KEEP_RE.search(text):
                continue
            if require and not all(t in text for t in require):
                continue
            out.append(text[:200])
        # 严格要求下无结果时放宽重试一次 (队名写法差异兜底)
        if not out and require:
            for b in blocks:
                text = re.sub(r"<[^>]+>", " ", b)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 30 or DROP_RE.search(text):
                    continue
                if filter_kw and not KEEP_RE.search(text):
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
        # 专业足球站点优先 (懂球帝/直播吧), 再放宽到全网; 结果必须含队名防错配
        queries = [
            f"{cn}队 伤停 2026 site:dongqiudi.com",
            f"{cn} 伤停名单 2026 site:zhibo8",
            f"{cn}队 伤停 2026",
            f"{cn} 伤停",
        ]
        got = []
        for q in queries:
            got = _search_bing(q, require=[cn])
            if got:
                break
            time.sleep(3)
        if not got:
            continue
        lines.append(f"[{team} / {cn}]")
        for s in got:
            lines.append(f"  - {_cn_source(s)}")
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

    # 裁判侦察 (八维之一: 官方任命未公布时明确写未公布, 不猜测)
    ref_lines = []
    for m in matches:
        h = _cn_name(m.get("home_team", ""))
        a = _cn_name(m.get("away_team", ""))
        if not h or not a:
            continue
        got = _search_bing(f"{h} {a} 主裁判 2026", filter_kw=False, require=[h, a])
        if got:
            ref_lines.append(f"[裁判] {h} vs {a}")
            for s in got[:2]:
                ref_lines.append(f"  - {_cn_source(s)}")
        time.sleep(3)
    if ref_lines:
        intel = intel + "\n\n=== 裁判信息侦察 (未经官方确认, 仅供参考) ===\n" + "\n".join(ref_lines)

    # 天气侦察 (八维之六: 无逐小时预报时按低置信处理)
    wx_lines = []
    for m in matches:
        h = _cn_name(m.get("home_team", ""))
        a = _cn_name(m.get("away_team", ""))
        if not h or not a:
            continue
        got = _search_bing(f"{h} {a} 比赛 天气 预报", filter_kw=False, require=[h, a])
        if got:
            wx_lines.append(f"[天气] {h} vs {a}")
            for s in got[:2]:
                wx_lines.append(f"  - {_cn_source(s)}")
        time.sleep(3)
    if wx_lines:
        intel = intel + "\n\n=== 天气侦察 (未经核实, 仅供参考) ===\n" + "\n".join(wx_lines)

    # 情报矛盾检测 (复盘经验库规则10: "暂无伤停"与伤停条目并存 → 交叉核验)
    conflict_lines = []
    for team in teams:
        cn = _cn_name(team)
        idx = intel.find(f"[{team} / ")
        if idx < 0:
            continue
        nxt = intel.find("\n[", idx + 1)
        sec = intel[idx: nxt if nxt > 0 else len(intel)]
        if ("暂无" in sec or "无伤停" in sec) and ("伤" in sec or "缺阵" in sec):
            conflict_lines.append(f"[冲突] {team}/{cn}: 情报同时含'暂无伤停'与伤停条目, 需交叉核验 (规则10)")
    # 始终写入检测块 (自检表B5要求可查)
    if conflict_lines:
        intel = intel + "\n\n=== 情报矛盾检测 (复盘经验库规则10) ===\n" + "\n".join(conflict_lines)
    else:
        intel = intel + "\n\n=== 情报矛盾检测 (复盘经验库规则10) ===\n(本日未发现矛盾条目)"
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
