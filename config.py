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
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


# Auto-load on import
load_env()


def get(key: str, default: str = "") -> str:
    """Get environment variable."""
    return os.environ.get(key, default)


# API keys
ODDS_API_KEY = get("ODDS_API_IO_KEY", "")
ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY", "")
