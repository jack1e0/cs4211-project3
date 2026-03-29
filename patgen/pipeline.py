"""Orchestrate Stage 1 (NL brief) → Stage 2 (PAT-style text)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from patgen.client import (
    complete_chat,
    stage1_system_message,
    stage2_system_message,
)
from patgen.config import Config


def infer_kind(path: Path, explicit: str | None) -> str:
    if explicit:
        e = explicit.lower().strip()
        if e not in ("eventb", "rust"):
            raise ValueError("--kind must be eventb or rust")
        return e
    suf = path.suffix.lower()
    if suf == ".rs":
        return "rust"
    return "eventb"


@dataclass
class RunResult:
    brief: str
    pat_source: str


def run_pipeline(path: Path, cfg: Config, *, kind: str | None = None) -> RunResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    input_kind = infer_kind(path, kind)
    user1 = f"File path (context only): {path.name}\n\n---\n\n{text}"

    brief = complete_chat(
        cfg,
        system=stage1_system_message(input_kind),
        user=user1,
        temperature=cfg.temperature_stage1,
    )

    user2 = brief
    pat_source = complete_chat(
        cfg,
        system=stage2_system_message(cfg),
        user=user2,
        temperature=cfg.temperature_stage2,
    )

    return RunResult(brief=brief, pat_source=pat_source)
