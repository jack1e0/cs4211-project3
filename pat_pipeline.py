#!/usr/bin/env python3
"""
Rust / Event-B  ->  PAT Model Pipeline  (DeepSeek version)
============================================================
Usage:
    python pat_pipeline.py <input_file> [--type rust|eventb] [--out output.csp]

Requirements:
    pip install openai

The pipeline runs 4 stages:
  1. Planning LLM   - deepseek-r1:14b: extracts constants, vars, guards,
                      actions and builds a detailed code-gen plan
  2. Code-Gen LLM   - deepseek-r1:14b: translates the plan into PAT (.csp)
  3. Static Lint    - checks PAT syntax rules without needing PAT installed
  4. Repair Loop    - feeds lint errors back to the LLM and iterates (<=5 times)
"""

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    sys.exit("openai package not found. Run: pip install openai")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLANNING_MODEL = "deepseek-r1:14b"
CODEGEN_MODEL  = "deepseek-r1:14b"

MAX_REPAIR_LOOPS = 5
MAX_TOKENS       = 8192

CLIENT = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLANNING_SYSTEM = textwrap.dedent("""\
You are a formal-methods expert who specialises in translating concurrent systems
into PAT (Process Analysis Toolkit) CSP# models.

Your job is STAGE 1 - PLANNING.
Read the supplied source code or Event-B model and produce a structured JSON
analysis that a separate code-generation model will use to write the PAT file.

Output ONLY valid JSON (no markdown fences, no extra text) with this schema:
{
  "system_type": "rust" | "eventb",
  "system_name": "<short identifier>",
  "constants": [{"name": "...", "value": "...", "comment": "..."}],
  "variables": [{"name": "...", "type": "int|bool|enum", "init": "...", "range": "..."}],
  "processes": [
    {
      "name": "<ProcessName>",
      "role": "<Actor|Gate|Resource|Monitor>",
      "states_encoded_as": "<variable name or inline description>",
      "transitions": [
        {
          "label": "<event_name>",
          "guard": "<PAT guard expression, e.g. [lock == 0]>",
          "actions": ["<var = expr>"],
          "next_state": "<optional symbolic name>"
        }
      ]
    }
  ],
  "composition": "<PAT composition expression, e.g. P1() || P2()>",
  "assertions": [
    {
      "id": "A1",
      "kind": "deadlockfree|reaches|invariant|LTL",
      "description": "<human description>",
      "pat_snippet": "#assert System deadlockfree;"
    }
  ],
  "translation_notes": ["<any tricky mapping decisions>"]
}
""")

CODEGEN_SYSTEM = textwrap.dedent("""\
You are a PAT (Process Analysis Toolkit) CSP# code generator.
You will receive a structured JSON plan and must output a complete, syntactically
valid PAT (.csp) file - nothing else.

PAT CSP# syntax rules you MUST follow:
- Variables declared with:  var <n> = <init>;
- Defines / macros:         #define <n> <expr>;
- Process definition:       <n>() = <body>;
- Guarded transition:       [<guard>] event -> Process()
- Sequential:               e1 -> e2 -> Process()
- Choice:                   P1() [] P2()
- Interleaving:             P1() ||| P2()
- Parallel composition:     P1() || P2()
- Atomic block:             atomic { <stmts> }
- If-else inside atomic:    if (<cond>) { stmts } else { stmts }
- Assignment inside atomic: <var> = <expr>;   (use = NOT :=)
- Skip:                     Skip
- Stop:                     Stop
- Assertions:               #assert <System> <property>;

Do NOT output anything except the PAT file content.
Do NOT wrap output in markdown code fences.
""")

REPAIR_SYSTEM = textwrap.dedent("""\
You are a PAT CSP# debugging assistant.
You will receive a PAT model that has syntax or logic errors, plus an error report.
Output ONLY the corrected, complete PAT file - no explanation, no markdown fences.
""")

# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------

def call_llm(model: str, system: str, messages: list) -> str:
    """Call DeepSeek API. For deepseek-reasoner, reasoning content is stripped."""
    full_messages = [{"role": "system", "content": system}] + messages

    # deepseek-reasoner doesn't support system messages in some contexts,
    # so we fold it into the first user message if needed
    resp = CLIENT.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=full_messages,
    )

    raw = resp.choices[0].message.content
    if raw is None:
        # deepseek-reasoner sometimes puts output only in reasoning_content
        raw = getattr(resp.choices[0].message, "reasoning_content", "") or ""
    raw = raw.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw)
    return raw

# ---------------------------------------------------------------------------
# Stage 1 - Planning
# ---------------------------------------------------------------------------

def stage_planning(source_code: str, hint: str) -> dict:
    print("[1/4] Planning - extracting model structure ...")
    print("      (using deepseek-reasoner, may take 30-60s)")
    raw = call_llm(
        PLANNING_MODEL,
        PLANNING_SYSTEM,
        [{"role": "user", "content": f"System type hint: {hint}\n\n---SOURCE---\n{source_code}"}]
    )
    try:
        plan = json.loads(raw)
        print("  Plan extracted successfully.")
    except json.JSONDecodeError as e:
        print(f"  Warning: model returned non-JSON, saving raw output.\n  Error: {e}")
        plan = {"_raw_plan": raw}
    return plan

# ---------------------------------------------------------------------------
# Stage 2 - Code Generation
# ---------------------------------------------------------------------------

def stage_codegen(plan: dict, source_code: str) -> str:
    print("[2/4] Code generation - translating plan to PAT ...")
    plan_json = json.dumps(plan, indent=2)
    pat = call_llm(
        CODEGEN_MODEL,
        CODEGEN_SYSTEM,
        [{"role": "user", "content": (
            f"Generate a PAT (.csp) model from this plan.\n\n"
            f"---PLAN---\n{plan_json}\n\n"
            f"---ORIGINAL SOURCE (for reference)---\n{source_code[:3000]}"
        )}]
    )
    print("  PAT model generated.")
    return pat

# ---------------------------------------------------------------------------
# Stage 3 - Static Lint
# ---------------------------------------------------------------------------

LINT_RULES = [
    (r":=",                  "Use '=' not ':=' for assignment inside atomic blocks"),
    (r"#assert\s+\w+\s*$",  "#assert must end with a property keyword (deadlockfree / reaches / ...)"),
    (r"^var\s+\w+\s*;",     "var declaration missing initialiser '= <value>'"),
]

def stage_lint(pat_code: str) -> list:
    print("[3/4] Lint - checking PAT syntax ...")
    errors = []
    for i, line in enumerate(pat_code.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for pattern, msg in LINT_RULES:
            if re.search(pattern, stripped):
                errors.append(f"Line {i}: {msg}  ->  {stripped[:80]}")

    # Check that called processes are defined
    defined  = set(re.findall(r"^(\w+)\s*\(", pat_code, re.MULTILINE))
    called   = set(re.findall(r"\b([A-Z]\w*)\s*\(\s*\)", pat_code))
    keywords = {"Skip", "Stop"}
    for m in called - defined - keywords:
        errors.append(f"Process '{m}()' is called but never defined")

    if errors:
        print(f"  Found {len(errors)} issue(s).")
    else:
        print("  No lint issues found - OK")
    return errors

# ---------------------------------------------------------------------------
# Stage 4 - Repair Loop
# ---------------------------------------------------------------------------

def stage_repair(pat_code: str, errors: list, source_code: str) -> str:
    print("[4/4] Repair loop ...")
    fixed = pat_code
    prev_errors = errors

    for attempt in range(1, MAX_REPAIR_LOOPS + 1):
        prompt = (
            "Fix all errors in this PAT model.\n\n"
            "---ERRORS---\n" + "\n".join(prev_errors) +
            "\n\n---PAT MODEL---\n" + fixed +
            "\n\n---ORIGINAL SOURCE (reference)---\n" + source_code[:2000]
        )
        fixed = call_llm(CODEGEN_MODEL, REPAIR_SYSTEM, [{"role": "user", "content": prompt}])
        new_errors = stage_lint(fixed)

        if not new_errors:
            print(f"  Repaired after {attempt} iteration(s).")
            return fixed

        print(f"  Attempt {attempt}/{MAX_REPAIR_LOOPS}: {len(new_errors)} error(s) remain.")
        prev_errors = new_errors

    print("  Max repair attempts reached. Returning best effort.")
    return fixed

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def detect_type(path: Path) -> str:
    text = path.read_text(errors="replace").lower()
    if "machine" in text or "invariants" in text or path.suffix in (".json", ".eventb"):
        return "eventb"
    return "rust"

def main():
    global PLANNING_MODEL, CODEGEN_MODEL

    parser = argparse.ArgumentParser(
        description="Translate a Rust or Event-B file into a PAT CSP# model using DeepSeek."
    )
    parser.add_argument("input", help="Path to Rust (.rs) or Event-B (.json/.eventb) file")
    parser.add_argument("--type", choices=["rust", "eventb"], default=None,
                        help="Override auto-detection")
    parser.add_argument("--out", default=None,
                        help="Output .csp filename (default: <input_stem>.csp)")
    parser.add_argument("--model-plan", default=None,
                        help=f"Override planning model (default: {PLANNING_MODEL})")
    parser.add_argument("--model-code", default=None,
                        help=f"Override codegen model (default: {CODEGEN_MODEL})")
    args = parser.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        sys.exit(
            "Error: DEEPSEEK_API_KEY not set.\n\n"
            "To get your free key ($5 credits on signup):\n"
            "  1. Go to https://platform.deepseek.com\n"
            "  2. Sign up -> API Keys -> Create API key\n\n"
            "Then set it:\n"
            "  Mac/Linux:  export DEEPSEEK_API_KEY='sk-...'\n"
            "  Windows:    set DEEPSEEK_API_KEY=sk-..."
        )

    if args.model_plan:
        PLANNING_MODEL = args.model_plan
    if args.model_code:
        CODEGEN_MODEL = args.model_code

    src_path = Path(args.input)
    if not src_path.exists():
        sys.exit(f"Error: file not found: {src_path}")

    source_code = src_path.read_text(errors="replace")
    src_type    = args.type or detect_type(src_path)
    out_path    = Path(args.out) if args.out else src_path.with_suffix(".csp")

    print(f"\n{'='*60}")
    print(f"  PAT Pipeline  |  {src_path.name}  ->  {out_path.name}")
    print(f"  Source type   : {src_type}")
    print(f"  Planning model: {PLANNING_MODEL}")
    print(f"  Codegen model : {CODEGEN_MODEL}")
    print(f"{'='*60}\n")

    plan     = stage_planning(source_code, src_type)
    pat_code = stage_codegen(plan, source_code)
    errors   = stage_lint(pat_code)

    if errors:
        pat_code = stage_repair(pat_code, errors, source_code)
    else:
        print("[4/4] Repair loop - skipped (no errors)")

    # --- Versioned output ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem      = src_path.stem
 
    # runs/<stem>/  directory holds all attempts
    runs_dir  = Path("runs") / stem
    runs_dir.mkdir(parents=True, exist_ok=True)
 
    versioned_csp  = runs_dir / f"{stem}_{timestamp}.csp"
    versioned_plan = runs_dir / f"{stem}_{timestamp}_plan.json"
    versioned_csp.write_text(pat_code)
    versioned_plan.write_text(json.dumps(plan, indent=2))
 
    # Also write/overwrite the "latest" copy next to the source file
    out_path.write_text(pat_code)
 
    # Append a line to the run log
    log_path = runs_dir / "run_log.jsonl"
    log_entry = {
        "timestamp"     : timestamp,
        "source_file"   : str(src_path),
        "source_type"   : src_type,
        "planning_model": PLANNING_MODEL,
        "codegen_model" : CODEGEN_MODEL,
        "lint_errors"   : len(errors),
        "output_csp"    : str(versioned_csp),
        "output_plan"   : str(versioned_plan),
    }
    with log_path.open("a") as f:
        f.write(json.dumps(log_entry) + "\n")
 
    print(f"\n{'='*60}")
    print(f"  Latest PAT model ->  {out_path}")
    print(f"  Versioned copy   ->  {versioned_csp}")
    print(f"  Plan JSON        ->  {versioned_plan}")
    print(f"  Run log          ->  {log_path}")
    print(f"{'='*60}")
    print("\nAll attempts are saved in the runs/ folder.")
    print("Next: open the .csp in PAT Model Checker and run the #assert statements.")
    print("If PAT gives counter-examples, paste them as comments in your source")
    print("file and re-run - the repair loop will incorporate them.\n")
 

if __name__ == "__main__":
    main()