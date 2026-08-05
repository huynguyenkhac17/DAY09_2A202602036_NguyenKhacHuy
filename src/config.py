"""Cau hinh runtime.

README muc 9: ten model PHAI nam trong source code (khong phai .env) de cham diem,
va phai khop voi logging/metadata.json.
"""

from __future__ import annotations

import os
import pathlib

# --- Model (<= 10B parameters theo rang buoc de bai) ---------------------------
LLM_PROVIDER = "groq"
LLM_MODEL = "llama-3.1-8b-instant"  # 8B params <= 10B
LLM_PARAM_SIZE = "8B"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 512
LLM_TIMEOUT_S = 30
LLM_MAX_RETRIES = 3

# --- Duong dan -----------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
LOG_DIR = ROOT / "logging"
TRACE_PATH = LOG_DIR / "trace.jsonl"
METADATA_PATH = LOG_DIR / "metadata.json"


def api_key() -> str | None:
    """Doc GROQ_API_KEY tu env. Tra None neu chua co (pipeline van chay duoc
    o che do deterministic-only, xem src/llm.py)."""
    return os.getenv("GROQ_API_KEY") or None


def llm_enabled() -> bool:
    return api_key() is not None
