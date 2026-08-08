"""
足球分析智能体 - 主入口

用法:
    # 启动 Web 服务
    python main.py serve

    # 命令行对话
    python main.py chat

    # 快速预测
    python main.py predict Arsenal "Manchester City"
"""
from __future__ import annotations

import asyncio
import sys

import uvicorn
from loguru import logger

from src.utils.config import config

# 配置日志
logger.add(
    "logs/football_agent_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
)


def serve() -> None:
    """启动 Web 服务"""
    missing = config.validate()
    if missing:
        logger.error(f"缺少必要配置: {', '.join(missing)}")
        logger.info("请创建 .env 文件并填入 API Key (参考 .env.example)")
        sys.exit(1)

    logger.info(f"启动足球分析智能体 Web 服务: http://{config.HOST}:{config.PORT}")
    uvicorn.run(
        "src.web.app:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
        log_level="info",
    )


def chat() -> None:
    """命令行对话模式"""
    from src.agent.football_agent import FootballAgent

    missing = config.validate()
    if missing:
        logger.error(f"缺少必要配置: {', '.join(missing)}")
        sys.exit(1)

    agent = FootballAgent()

    async def _chat():
        print("\n" + "=" * 60)
        print("⚽  足球分析智能体 - 命令行模式")
        print("=" * 60)
        print("输入 'quit' 退出, 'clear' 清空对话历史")
        print()

        while True:
            try:
                user_input = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见!")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("再见!")
                break
            if user_input.lower() == "clear":
                agent.clear_history()
                print("对话历史已清空\n")
                continue

            reply = await agent.chat(user_input)
            print(f"\nAI: {reply}\n")
            print("-" * 60)

    asyncio.run(_chat())


def predict() -> None:
    """快速预测命令"""
    from src.agent.football_agent import predict_match_simple

    if len(sys.argv) < 4:
        print("用法: python main.py predict <主队> <客队>")
        print("示例: python main.py predict Arsenal \"Manchester City\"")
        sys.exit(1)

    home = sys.argv[2]
    away = sys.argv[3]

    async def _predict():
        result = await predict_match_simple(home, away)
        print(f"\n📊 {result['home_team']} vs {result['away_team']}")
        print(f"   主胜: {result['prediction']['home_win']}%")
        print(f"   平局: {result['prediction']['draw']}%")
        print(f"   客胜: {result['prediction']['away_win']}%")
        print(f"   推荐: {result['prediction']['recommendation']}")
        print(f"   预期进球: {result['expected_goals']['home']} - {result['expected_goals']['away']}")
        print(f"   最可能比分: {', '.join(s['score'] + ' (' + s['pct'] + ')' for s in result['likely_scores'][:3])}")

    asyncio.run(_predict())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py serve    启动 Web 服务")
        print("  python main.py chat     命令行对话")
        print("  python main.py predict <主队> <客队>  快速预测")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "serve":
        serve()
    elif command == "chat":
        chat()
    elif command == "predict":
        predict()
    else:
        print(f"未知命令: {command}")
        sys.exit(1)
