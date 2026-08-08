"""
历史赔率工具 — football-data.co.uk CSV 数据

数据来源: https://www.football-data.co.uk/
覆盖: 英超/西甲/德甲/意甲/法甲 近5赛季
频率: 每周自动检查更新
"""
from __future__ import annotations

import os
import csv
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from loguru import logger

# ============================================================
# 配置
# ============================================================

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "historical_odds"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# football-data.co.uk 联赛代码
LEAGUE_CODES = {
    "E0": "英超", "E1": "英冠", "E2": "英甲", "E3": "英乙",
    "SP1": "西甲", "SP2": "西乙",
    "D1": "德甲", "D2": "德乙",
    "I1": "意甲", "I2": "意乙",
    "F1": "法甲", "F2": "法乙",
    "N1": "荷甲",
    "P1": "葡超",
    "SC0": "苏超",
    "T1": "土超",
    "B1": "比甲",
    "G1": "希腊超",
}

# 可用的博彩公司列名
BOOKMAKER_COLS = {
    "B365": "Bet365",
    "PS": "Pinnacle",
    "WH": "William Hill",
    "VC": "VC Bet",
    "IW": "Interwetten",
    "LB": "Ladbrokes",
    "BS": "Blue Square",
    "SJ": "Stan James",
    "GB": "Gamebookers",
}

# 当前赛季代码 (如 2526 = 2025-26)
def _season_code(season_start_year: int) -> str:
    """赛季 → football-data.co.uk 两位年份码, 如 2025 → '2526'"""
    y1 = str(season_start_year)[-2:]
    y2 = str(season_start_year + 1)[-2:]
    return f"{y1}{y2}"

# ============================================================
# CSV 下载
# ============================================================

def download_season(league_code: str, season_start: int | None = None) -> str | None:
    """下载单个联赛单赛季 CSV, 返回文件路径

    Args:
        league_code: 联赛代码 (如 'E0'=英超)
        season_start: 赛季起始年 (如 2021), 默认=当前赛季

    Returns:
        本地CSV文件路径, 失败返回 None
    """
    if season_start is None:
        now = datetime.now()
        season_start = now.year if now.month >= 7 else now.year - 1

    code = _season_code(season_start)
    url = f"https://www.football-data.co.uk/mmz4281/{code}/{league_code}.csv"
    fname = f"{league_code}_{season_start}_{season_start+1}.csv"
    fpath = DATA_DIR / fname

    # 如果已存在且是最近7天下载的, 跳过
    if fpath.exists():
        age = time.time() - fpath.stat().st_mtime
        if age < 7 * 86400:
            logger.debug(f"跳过 (最近已下载): {fname}")
            return str(fpath)

    try:
        logger.info(f"下载: {url}")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        # 检查是否是有效CSV (有些赛季可能不存在)
        if "html" in resp.text[:100].lower() or len(resp.text) < 500:
            logger.warning(f"无效数据: {url}")
            return None

        fpath.write_text(resp.text, encoding="utf-8", errors="replace")
        logger.info(f"已保存: {fname} ({len(resp.text)} bytes)")
        return str(fpath)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"赛季数据不存在: {url}")
        else:
            logger.error(f"下载失败: {e}")
        return None
    except Exception as e:
        logger.error(f"下载失败: {e}")
        return None


def download_all(seasons: int = 5) -> dict[str, list[str]]:
    """批量下载所有配置联赛的近N赛季数据

    Returns:
        {联赛名: [CSV文件路径列表]}
    """
    now = datetime.now()
    current_season = now.year if now.month >= 7 else now.year - 1
    results: dict[str, list[str]] = {}

    for code, name in LEAGUE_CODES.items():
        # 只下载五大联赛
        if code not in ("E0", "SP1", "D1", "I1", "F1"):
            continue

        paths = []
        for y in range(current_season - seasons + 1, current_season + 1):
            path = download_season(code, y)
            if path:
                paths.append(path)
            time.sleep(0.3)  # 礼貌请求间隔

        if paths:
            results[name] = paths
            logger.info(f"{name}: {len(paths)}/{seasons} 赛季已下载")

    return results


# ============================================================
# 查询接口
# ============================================================

def get_historical_odds(
    league: str,
    season_start: int,
    home_team: str,
    away_team: str,
) -> dict[str, Any] | None:
    """从本地CSV查询某场比赛的终盘赔率

    Args:
        league:    联赛代码 ('E0'/'SP1'/'D1'/'I1'/'F1')
        season_start: 赛季起始年
        home_team: 主队名称 (需与CSV中的名称匹配)
        away_team: 客队名称

    Returns:
        {
            "date": "05/08/2026",
            "home_team": "Arsenal",
            "away_team": "Liverpool",
            "full_time": {"home": 2, "away": 1},
            "odds": {
                "bet365": {"home": 2.10, "draw": 3.50, "away": 3.25},
                "pinnacle": {"home": 2.15, "draw": 3.45, "away": 3.20},
                ...
            }
        }
        未找到返回 None
    """
    # 尝试加载本地CSV
    code = _season_code(season_start)
    fname = f"{league}_{season_start}_{season_start+1}.csv"
    fpath = DATA_DIR / fname

    # 如果本地没有, 尝试下载
    if not fpath.exists():
        fpath_str = download_season(league, season_start)
        if not fpath_str:
            return None
        fpath = Path(fpath_str)

    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(text.splitlines())

        # 模糊匹配球队名 (CSV中名称可能略有差异)
        home_lower = home_team.lower().strip()
        away_lower = away_team.lower().strip()

        for row in reader:
            csv_home = row.get("HomeTeam", "").lower().strip()
            csv_away = row.get("AwayTeam", "").lower().strip()

            # 模糊匹配: 包含关系
            if (home_lower in csv_home or csv_home in home_lower) and \
               (away_lower in csv_away or csv_away in away_lower):

                odds = {}
                for col_prefix, name in BOOKMAKER_COLS.items():
                    h_col = f"{col_prefix}H"
                    d_col = f"{col_prefix}D"
                    a_col = f"{col_prefix}A"
                    if h_col in row and row[h_col]:
                        try:
                            odds[name] = {
                                "home": float(row[h_col]),
                                "draw": float(row[d_col]),
                                "away": float(row[a_col]),
                            }
                        except (ValueError, KeyError):
                            continue

                fthg = int(row.get("FTHG", 0) or 0)
                ftag = int(row.get("FTAG", 0) or 0)

                return {
                    "date": row.get("Date", ""),
                    "home_team": row.get("HomeTeam", ""),
                    "away_team": row.get("AwayTeam", ""),
                    "full_time": {"home": fthg, "away": ftag},
                    "half_time": {
                        "home": int(row.get("HTHG", 0) or 0),
                        "away": int(row.get("HTAG", 0) or 0),
                    },
                    "odds": odds,
                    "source": f"football-data.co.uk {fname}",
                }

        return None

    except Exception as e:
        logger.error(f"查询CSV失败: {e}")
        return None


def search_historical_matches(
    league: str = "E0",
    home_team: str | None = None,
    away_team: str | None = None,
    seasons_back: int = 3,
) -> list[dict]:
    """搜索历史比赛 (支持按球队名筛选)

    Args:
        league:       联赛代码
        home_team:    主队名筛选 (可选)
        away_team:    客队名筛选 (可选)
        seasons_back: 回溯赛季数

    Returns:
        匹配的比赛列表
    """
    now = datetime.now()
    current_season = now.year if now.month >= 7 else now.year - 1
    results = []

    for y in range(current_season - seasons_back + 1, current_season + 1):
        fname = f"{league}_{y}_{y+1}.csv"
        fpath = DATA_DIR / fname

        if not fpath.exists():
            fpath_str = download_season(league, y)
            if not fpath_str:
                continue
            fpath = Path(fpath_str)

        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            reader = csv.DictReader(text.splitlines())

            for row in reader:
                csv_home = row.get("HomeTeam", "").lower()
                csv_away = row.get("AwayTeam", "").lower()

                if home_team and home_team.lower() not in csv_home:
                    continue
                if away_team and away_team.lower() not in csv_away:
                    continue

                fthg = row.get("FTHG", "")
                ftag = row.get("FTAG", "")
                results.append({
                    "date": row.get("Date", ""),
                    "season": f"{y}-{y+1}",
                    "home_team": row.get("HomeTeam", ""),
                    "away_team": row.get("AwayTeam", ""),
                    "score": f"{fthg}-{ftag}" if fthg and ftag else "",
                    "source": fname,
                })

                if len(results) >= 100:
                    return results

        except Exception as e:
            logger.error(f"搜索失败 {fname}: {e}")
            continue

    return results
