from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value


# ── OpenAI ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Celery / Redis ────────────────────────────────────────────────────────────
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# ── Storage ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("DATA_DIR", "data"))
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TMP_DIR = BASE_DIR / "tmp"

# ── Whisper ───────────────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")

# ── Clip selection ────────────────────────────────────────────────────────────
MAX_CLIPS: int = int(os.getenv("MAX_CLIPS", "5"))
MIN_CLIP_SECONDS: int = int(os.getenv("MIN_CLIP_SECONDS", "20"))
MAX_CLIP_SECONDS: int = int(os.getenv("MAX_CLIP_SECONDS", "90"))