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
# API-Football (api-sports.io 直连) — 伤停/首发/xG 数据源
FOOTBALL_RAPIDAPI_KEY = get("FOOTBALL_RAPIDAPI_KEY", "")
# football-data.org v4 — 赛果/赛程 (注册即发key, 大陆可直连)
FOOTBALL_DATA_API_KEY = get("FOOTBALL_DATA_API_KEY", "")

# 聚焦联赛白名单 (2026-08-16 起: 只关注五大联赛)
# 如需加联赛, 逗号分隔添加代码即可 (如 PL,PD,BL1,SA,FL1,DED)
FOCUS_LEAGUES = [x.strip() for x in get("FOCUS_LEAGUES", "PL,PD,BL1,SA,FL1").split(",") if x.strip()]

# 次级联赛 (升班马跨级先验样本: 纳入训练, 顶级联赛出战时降权, 不直接平移)
SECOND_TIER_LEAGUES = ["PD2", "ELC", "BL2", "SB", "FL2"]

# 预测/下注范围: 只做五大联赛+欧冠, 其他一律不参与 (2026-09-09 用户拍板)
PREDICT_LEAGUES = list(FOCUS_LEAGUES) + ["UCL"]

# football-data.org v4 的联赛代码 (注意: 欧冠在那边叫 CL, 我们内部叫 UCL)
# 2026-09-11 加: /v4/matches 不传 competitions 参数会返回**全世界所有比赛**
# (含 U19 青年队/预备队/女足/爱沙尼亚/香港等), 之前每天误拉 200~1300 场,
# 是赛果数据污染和青年队误结算的根源。传了之后服务端就只返回这些联赛。
FOOTBALL_DATA_COMPETITIONS = "PL,PD,BL1,SA,FL1,CL"

# 投注资金池 (元) — 看好栏建议注额 = 资金池 × 凯利 ÷ 4
BANKROLL = float(get("BANKROLL", "1000"))

