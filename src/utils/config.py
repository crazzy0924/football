"""
配置管理模块
加载环境变量和应用配置
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)


class Config:
    """全局配置"""
    # --- Anthropic ---
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-fable-5")

    # --- 足球数据 API ---
    FOOTBALL_DATA_API_KEY: str = os.getenv("FOOTBALL_DATA_API_KEY", "")
    FOOTBALL_RAPIDAPI_KEY: str = os.getenv("FOOTBALL_RAPIDAPI_KEY", "")

    # --- 服务器 ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # --- 缓存 ---
    CACHE_DIR: Path = Path(__file__).resolve().parents[2] / ".cache"

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置，返回缺失项列表"""
        missing = []
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        return missing


config = Config()
