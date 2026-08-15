"""
Configuration v3.0

Loads environment variables from .env file.
Minimal — no more scattered API key lookups.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env():
    """Load .env file if it exists."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


# 导入时自动加载
load_env()


def get(key: str, default: str = "") -> str:
    """Get environment variable."""
    return os.environ.get(key, default)


# API keys
# the-odds-api.com (v4) — 32位密钥，odds_fetcher + fetch_pinnacle 使用
THE_ODDS_API_KEY = get("ODDS_API_KEY", "")
# odds-api.io (v3) — 64位密钥，旧版；优先用 the-odds-api.com
ODDS_API_IO_KEY = get("ODDS_API_IO_KEY", "")
# 向后兼容别名
ODDS_API_KEY = THE_ODDS_API_KEY or ODDS_API_IO_KEY
ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY", "")
# DeepSeek — Phase 4 LLM分析师优先provider (deepseek-harness接入)
DEEPSEEK_API_KEY = get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = get("DEEPSEEK_MODEL", "deepseek-v4-pro")
# API-Football (RapidAPI) — 伤停/首发/xG 数据源
FOOTBALL_RAPIDAPI_KEY = get("FOOTBALL_RAPIDAPI_KEY", "")
# football-data.org v4 — 赛果/赛程 (注册即发key, 大陆可直连)
FOOTBALL_DATA_API_KEY = get("FOOTBALL_DATA_API_KEY", "")

# 聚焦联赛白名单 (2026-08-16 起: 只关注五大联赛)
# 如需加联赛, 逗号分隔添加代码即可 (如 PL,PD,BL1,SA,FL1,DED)
FOCUS_LEAGUES = [x.strip() for x in get("FOCUS_LEAGUES", "PL,PD,BL1,SA,FL1").split(",") if x.strip()]

