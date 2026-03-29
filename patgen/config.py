"""Load settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Runtime configuration for OpenAI calls and optional few-shot text."""

    api_key: str | None
    model: str
    temperature_stage1: float
    temperature_stage2: float
    debug: bool
    #: Optional short examples concatenated into Stage 2 system context (not RAG).
    few_shot_system_addon: str | None


def load_config() -> Config:
    key = os.environ.get("OPENAI_API_KEY") or None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    few = os.environ.get("PATGEN_FEW_SHOT")
    if few:
        few_stripped = few.strip() or None
    else:
        few_stripped = None
    return Config(
        api_key=key,
        model=model,
        temperature_stage1=_env_float("OPENAI_TEMP_STAGE1", 0.2),
        temperature_stage2=_env_float("OPENAI_TEMP_STAGE2", 0.1),
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        few_shot_system_addon=few_stripped,
    )
