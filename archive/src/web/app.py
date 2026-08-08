"""
FastAPI Web 应用
提供 REST API 和 Web 界面
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.agent.football_agent import FootballAgent, predict_match_simple
from src.agent.tools import get_standings, search_matches

# 创建 FastAPI 应用
app = FastAPI(
    title="足球分析智能体",
    description="基于 AI 的足球比赛预测与分析系统",
    version="1.0.0",
)

# Agent 实例 (单例)
agent: FootballAgent | None = None

# 模板目录
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
async def startup() -> None:
    global agent
    try:
        agent = FootballAgent()
        logger.info("足球分析智能体已就绪")
    except Exception as e:
        logger.error(f"Agent 初始化失败: {e}")
        agent = None


# ---- 页面路由 ----

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """主页面"""
    html_path = TEMPLATE_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>足球分析智能体</h1><p>模板文件缺失</p>"


# ---- API 路由 ----

@app.post("/api/chat")
async def api_chat(request: Request) -> JSONResponse:
    """与智能体对话"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent 未就绪, 请检查 API Key")

    data = await request.json()
    message = data.get("message", "")

    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    try:
        reply = await agent.chat(message)
        return JSONResponse({"reply": reply, "status": "ok"})
    except Exception as e:
        logger.error(f"API 错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predict")
async def api_predict(request: Request) -> JSONResponse:
    """快速预测接口 (不使用 Agent)"""
    data = await request.json()
    home_team = data.get("home_team", "")
    away_team = data.get("away_team", "")

    if not home_team or not away_team:
        raise HTTPException(status_code=400, detail="请提供主队和客队名称")

    result = await predict_match_simple(
        home_team=home_team,
        away_team=away_team,
        home_form=data.get("home_form"),
        away_form=data.get("away_form"),
    )
    return JSONResponse(result)


@app.get("/api/matches")
async def api_matches(competition: str = "PL", matchday: int | None = None) -> JSONResponse:
    """获取比赛列表"""
    result = await search_matches(competition=competition, matchday=matchday)
    return JSONResponse(result)


@app.get("/api/standings/{competition}")
async def api_standings(competition: str = "PL") -> JSONResponse:
    """获取积分榜"""
    result = await get_standings(competition=competition)
    return JSONResponse(result)


# ---- 健康检查 ----

@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "healthy" if agent else "degraded",
        "has_api_key": bool(agent and agent.client.api_key),
    })
