from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

def _load_csp_examples_addon(examples_dir: Path) -> str | None:
    if not examples_dir.is_dir():
        return None
    paths = sorted(examples_dir.glob("*.csp"))
    if not paths:
        return None
    chunks: list[str] = []
    for p in paths:
        chunks.append(f"\n\n// ---------- Reference: {p.name} ----------\n")
        chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    text = "".join(chunks).strip()
    return text or None


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
    api_key: str | None
    model: str
    temperature_stage1: float
    temperature_stage2: float
    csp_examples_addon: str | None

def load_config() -> Config:
    key = os.environ.get("OPENAI_API_KEY") or None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    csp_examples_dir = Path(__file__).resolve().parent.parent / "csp_examples"

    csp_addon = _load_csp_examples_addon(csp_examples_dir)

    return Config(
        api_key=key,
        model=model,
        temperature_stage1=_env_float("OPENAI_TEMP_STAGE1", 0.2),
        temperature_stage2=_env_float("OPENAI_TEMP_STAGE2", 0.2),
        csp_examples_addon=csp_addon
    )
