# -*- coding: utf-8 -*-
"""首页入口保底守卫: 确保 index.html 始终含「克劳德交叉预测」入口 (2026-09-11 新增)

背景: 首页 index.html 是静态维护文件, sky 重写首页时会丢掉独立交叉预测入口。
本模块幂等: 入口在→不动; 入口没了→自动补回。被 pre_push_check.py 在推送前调用,
所以无论首页怎么被重写, 推送出去的版本一定带入口。

用法: python pipeline/ensure_home_entry.py
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # sky日记/
LINK = "my_preds/latest.html"
HERO_LINK = '<a class="btn btn-ghost" href="my_preds/latest.html">克劳德交叉预测 \u2197</a>'
FOOT_LINK = '<a href="my_preds/latest.html">克劳德交叉预测</a>'


def ensure(idx_path=None) -> bool:
    """补回入口。返回 True=本次做了修复, False=已存在或无法修复。"""
    idx = Path(idx_path) if idx_path else (ROOT / "index.html")
    if not idx.exists():
        return False
    html = idx.read_text(encoding="utf-8")
    if LINK in html:  # 已有入口 → 不动 (不重复注入)
        return False

    orig = html
    # 1) Hero: 插到「查看最新预测」按钮之后 (cta-row 内)
    m = re.search(r"查看最新预测[\s\S]*?</button>", html)
    if m:
        html = html[:m.end()] + "\n        " + HERO_LINK + html[m.end():]
    # 2) 页脚: 插到 footer-links 导航里
    m2 = re.search(r'<nav class="footer-links"[^>]*>', html)
    if m2:
        html = html[:m2.end()] + "\n        " + FOOT_LINK + html[m2.end():]

    if html != orig:
        idx.write_text(html, encoding="utf-8")
        try:
            subprocess.run(["git", "add", "index.html"], cwd=str(ROOT), capture_output=True)
        except Exception:
            pass
        return True
    return False


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer") and not getattr(sys.stdout, "_dsh_utf8", False):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stdout._dsh_utf8 = True
    fixed = ensure()
    print("🔗 首页入口: " + ("已自动补回「克劳德交叉预测」" if fixed else "已存在, 无需处理"))
