"""Load settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _default_csp_examples_dir() -> Path:
    """Repo-root `csp_examples/` next to the `patgen` package."""
    return Path(__file__).resolve().parent.parent / "csp_examples"


def _load_csp_examples_addon(examples_dir: Path | None) -> str | None:
    if examples_dir is None or not examples_dir.is_dir():
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
    """Runtime configuration for OpenAI calls and optional few-shot text."""

    api_key: str | None
    model: str
    temperature_stage1: float
    temperature_stage2: float
    debug: bool
    #: `.csp` files from `csp_examples/` (or PATGEN_CSP_EXAMPLES_DIR), for Stage 2 syntax.
    csp_examples_addon: str | None

def load_config() -> Config:
    key = os.environ.get("OPENAI_API_KEY") or None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    csp_examples_dir: Path | None = None
    csp_flag = os.environ.get("PATGEN_CSP_EXAMPLES", "1").strip().lower()
    if csp_flag not in ("0", "false", "no", "off"):
        override = os.environ.get("PATGEN_CSP_EXAMPLES_DIR", "").strip()
        if override:
            csp_examples_dir = Path(override).expanduser()
        else:
            csp_examples_dir = _default_csp_examples_dir()
    csp_addon = _load_csp_examples_addon(csp_examples_dir)

    return Config(
        api_key=key,
        model=model,
        temperature_stage1=_env_float("OPENAI_TEMP_STAGE1", 0.2),
        temperature_stage2=_env_float("OPENAI_TEMP_STAGE2", 0.2),
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        csp_examples_addon=csp_addon
    )
