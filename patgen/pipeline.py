from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from patgen.client import (
    generate,
    stage1_prompt,
    stage2_prompt,
    stage3_prompt,
)
from patgen.config import Config


def infer_kind(path: Path) -> str:
    if path.suffix.lower() == ".rs":
        return "rust"
    return "eventb"


@dataclass
class RunResult:
    brief: str
    pat_source: str


def run_pipeline(path: Path, cfg: Config, *, assertions: str | None = None) -> RunResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    input_kind = infer_kind(path)
    user1 = f"File path (context only): {path.name}\n\n---\n\n{text}"

    brief = generate(
        cfg,
        system=stage1_prompt(input_kind),
        user=user1,
        temperature=cfg.temperature_stage1,
    )

    pat_source = generate(
        cfg,
        system=stage2_prompt(assertions=assertions),
        user=brief,
        temperature=cfg.temperature_stage2,
    )

    final_csp = generate(
        cfg,
        system=stage3_prompt(pat_source, cfg),
        user=pat_source,
        temperature=cfg.temperature_stage2,
    )

    return RunResult(brief=brief, pat_source=final_csp)
