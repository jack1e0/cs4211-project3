from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patgen.config import load_config
from patgen.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate PAT-style model text from Event-B text or Rust via OpenAI.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to Event-B-like .txt or .rs source file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write PAT source to this file (default: <input_stem>.csp next to the input file)",
    )
    parser.add_argument(
        "--dump-brief",
        type=Path,
        default=None,
        help="Also write Stage 1 natural-language brief to this path",
    )
    parser.add_argument(
        "--assertions",
        type=Path,
        default=None,
        help="Path to a text file containing manual PAT assertions to include in the model",
    )
    args = parser.parse_args(argv)

    path: Path = args.input
    if not path.is_file():
        print(f"patgen: not a file: {path}", file=sys.stderr)
        return 2

    try:
        cfg = load_config()
        assertions = args.assertions.read_text(encoding="utf-8") if args.assertions else None
        result = run_pipeline(path, cfg, assertions=assertions)
    except Exception as ex:
        print(f"patgen: {ex}", file=sys.stderr)
        return 1

    if args.dump_brief:
        args.dump_brief.write_text(result.brief + "\n", encoding="utf-8")

    out_path = args.output if args.output is not None else path.with_suffix(".csp")
    out_path.write_text(result.pat_source + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
