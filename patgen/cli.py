"""Command-line entry for patgen."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patgen.config import load_config
from patgen.pipeline import run_pipeline


def default_pat_output_path(input_path: Path) -> Path:
    """Same directory as input, stem plus `.out` (e.g. `model.txt` -> `model.out`)."""
    return input_path.with_suffix(".out")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate PAT-style model text from Event-B text or Rust via OpenAI (two stages).",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to Event-B-like .txt or .rs source file",
    )
    parser.add_argument(
        "--kind",
        choices=("eventb", "rust"),
        default=None,
        help="Override input kind (default: from extension, .rs → rust, else eventb)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write PAT source to this file (default: <input_stem>.out next to the input file)",
    )
    parser.add_argument(
        "--dump-brief",
        type=Path,
        default=None,
        help="Also write Stage 1 natural-language brief to this path",
    )
    args = parser.parse_args(argv)

    path: Path = args.input
    if not path.is_file():
        print(f"patgen: not a file: {path}", file=sys.stderr)
        return 2

    try:
        cfg = load_config()
        result = run_pipeline(path, cfg, kind=args.kind)
    except Exception as ex:  # noqa: BLE001 — CLI surfaces any failure
        print(f"patgen: {ex}", file=sys.stderr)
        return 1

    if args.dump_brief:
        args.dump_brief.write_text(result.brief + "\n", encoding="utf-8")

    out_path = args.output if args.output is not None else default_pat_output_path(path)
    out_path.write_text(result.pat_source + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
