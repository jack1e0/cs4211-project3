#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import re
from pathlib import Path
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PAT_EXE_PATH = r"/Users/tengcharmaine/Downloads/Process Analysis Toolkit 3.5.1/PAT3.Console.exe"

MODEL = "qwen2.5-coder:7b"
MAX_REPAIR_LOOPS = 5

CLIENT = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

# ---------------------------------------------------------------------------
# CSP# Syntax Reference
# Generic syntax patterns only — no domain-specific names or variables.
# The LLM uses this to learn HOW to write CSP#, not WHAT to write.
# NOTE: the initialisation event is 'ini' NOT 'init' — 'init' is reserved.
# ---------------------------------------------------------------------------
CSP_SYNTAX_REFERENCE = """
// SYNTAX REFERENCE — valid PAT3 CSP# patterns. Names/values are placeholders only.

// 1. Variable declarations — integers and integer arrays ONLY
var flag = 0;
var counter = 0;
var arr[4] = [0,0,0,0];

// 2. Init process — use event name 'ini' (NOT 'init' — that is a reserved word in PAT3)
Init() = ini{flag = 0; counter = 0;} -> Skip;

// 3. Conditional branching with []
//    [condition] guards the branch; {} block performs assignments on the event
ConditionalProc(t) =
    [flag == 0] event_a.t{flag = 1;} -> Skip
    []
    [flag == 1] event_b.t{flag = 0;} -> ConditionalProc(t);

// 4. Sequential steps chained with ->
SeqProc(t) =
    step_one.t{counter = counter + 1;} ->
    step_two.t{counter = counter - 1;} ->
    Skip;

// 5. Array element access
ArrayProc(t) =
    [arr[t] == 0] set.t{arr[t] = 1;} -> Skip
    []
    [arr[t] == 1] clear.t{arr[t] = 0;} -> ArrayProc(t);

// 6. Waiting / retrying (model blocking with recursion, NOT a wait queue object)
WaitProc(t) =
    [flag == 0] proceed.t{flag = 1;} -> Skip
    []
    [flag == 1] retry.t -> WaitProc(t);

// 7. Sequential composition of processes with ;
ComposedProc(t) =
    StepA(t);
    StepB(t);
    Skip;

// 8. Parallel composition with |||
// System() is always the top-level entry point and must be the last definition
System() = Init(); (Worker(1) ||| Worker(2) ||| Worker(3));
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_output(text):
    """
    Strips markdown fences and trailing prose.
    Anchors to the first structural PAT keyword.
    Never anchors on '#' alone — that would latch onto assertions
    and discard all process definitions.
    """
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    text = text.replace("```", "").strip()

    # Anchor to first var declaration or Process() = definition
    match = re.search(
        r"(var\s+\w|[A-Z]\w*\s*\(\s*\)\s*=|[A-Z]\w*\s*\(\s*\w+\s*\)\s*=).*",
        text, re.DOTALL
    )
    if match:
        text = match.group(0)

    # Strip trailing prose lines
    lines = text.splitlines()
    last_code_line = 0
    prose_starters = ("the ", "note", "this ", "here ", "above", "below", "in ", "as ", "so ")
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped and not any(stripped.startswith(p) for p in prose_starters):
            last_code_line = i
    text = "\n".join(lines[:last_code_line + 1])

    return text.strip()


def sanitize_body(csp_body):
    """
    Fix common LLM mistakes that PAT3 rejects:
    - 'init{' -> 'ini{' (init is a reserved internal event in PAT3)
    - true/false -> 1/0
    - Drop var lines with constructor syntax like WaitQueue(), UnsafeCell()
    """
    fixed_lines = []
    for line in csp_body.splitlines():
        # Fix reserved event name: init{ -> ini{
        # Use word boundary so we don't corrupt e.g. 'initialize'
        line = re.sub(r'\binit\s*\{', 'ini{', line)
        # Fix booleans
        line = re.sub(r'\btrue\b', '1', line)
        line = re.sub(r'\bfalse\b', '0', line)
        # Drop var lines with constructor calls
        if re.match(r'\s*var\s+\w+\s*=\s*\w+\(.*\)\s*;?', line):
            continue
        fixed_lines.append(line)
    return "\n".join(fixed_lines)


def strip_assertions(csp_content):
    """
    Remove all #define and #assert lines from the CSP body.
    We always re-append the canonical assertions file ourselves —
    never trust the LLM to copy them correctly.
    """
    lines = [
        l for l in csp_content.splitlines()
        if not l.strip().startswith("#define")
        and not l.strip().startswith("#assert")
    ]
    return "\n".join(lines).strip()


def append_assertions(csp_body, assertions):
    """Attach the canonical assertions block after the process definitions."""
    return csp_body.rstrip() + "\n\n" + assertions.strip() + "\n"


def build_variable_hint(assertions):
    """
    Extract runtime variable names referenced in #define expressions only.

    Key rules:
    - For #define lines: skip the macro name (LHS) entirely, parse only the
      boolean expression (RHS). This prevents macro names like
      'acq_prog_lock_held' from being declared as variables.
    - For #assert lines: skip entirely — they only reference macro names.

    Returns (scalars: sorted list, arrays: sorted list of base names).
    """
    keywords = {
        'reaches', 'deadlockfree', 'assert', 'define', 'System',
        'if', 'or', 'and', 'not', 'in', 'is', 'true', 'false', 'int',
        'skip', 'Stop', 'Init', 'ini'
    }
    scalars = set()
    arrays = set()

    for line in assertions.splitlines():
        stripped = line.strip()

        if stripped.startswith('#define'):
            # Skip the macro name — parse only the expression after it
            m = re.match(r'#define\s+\w+\s+(.*)', stripped)
            if not m:
                continue
            expr = m.group(1)
        elif stripped.startswith('#assert'):
            # Assert lines only reference macro names — skip entirely
            continue
        else:
            expr = stripped

        # Extract array accesses first (e.g. guard_live[1], in_critical[2])
        for m in re.finditer(r'\b([a-z][a-z_0-9]*)\[', expr):
            name = m.group(1)
            if name not in keywords:
                arrays.add(name)
                scalars.discard(name)

        # Extract plain variable names (skip anything already identified as array)
        for m in re.finditer(r'\b([a-z][a-z_0-9]*)\b', expr):
            name = m.group(1)
            if name not in keywords and len(name) > 1 and name not in arrays:
                scalars.add(name)

    return sorted(scalars), sorted(arrays)


def validate_structure(csp_content):
    """
    Sanity check before sending to PAT:
    - At least one process definition must exist.
    - Process definitions must appear before #assert lines.
    Returns (ok: bool, reason: str)
    """
    lines = csp_content.splitlines()
    first_assert = next(
        (i for i, l in enumerate(lines) if l.strip().startswith("#assert")), None
    )
    first_process = next(
        (i for i, l in enumerate(lines)
         if re.match(r"^[A-Z]\w*\s*\(.*?\)\s*=", l.strip())), None
    )

    if first_process is None:
        return False, "No process definitions found (e.g. 'System() = ...'). Output is likely assertions-only or malformed."

    if first_assert is not None and first_assert < first_process:
        return False, (
            f"Assertions appear before process definitions "
            f"(assert at line {first_assert+1}, process at line {first_process+1})."
        )

    return True, "OK"


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def generate_initial_model(source_code, assertions):
    """
    Ask the LLM to generate ONLY the CSP# process body (no assertions).
    Variable hints are derived from #define expression RHS only,
    so macro names are never mistakenly declared as variables.
    Assertions are appended from the canonical file afterward.
    """
    print("[1] Generating initial PAT model...")

    scalars, arrays = build_variable_hint(assertions)
    scalar_decls = "\n".join(f"var {v} = 0;" for v in scalars)
    array_decls  = "\n".join(f"var {v}[4] = [0,0,0,0];" for v in arrays)
    var_hint = (scalar_decls + "\n" + array_decls).strip()

    prompt = f"""
You are translating source code into a PAT3 CSP# model.

The reference below shows ONLY valid PAT3 CSP# syntax patterns.
The variable names and process names in the reference are generic placeholders —
do NOT copy them. Derive appropriate names and behaviour from the source code.

### PAT3 SYNTAX REFERENCE (patterns to follow, not content to copy):
{CSP_SYNTAX_REFERENCE}

### SOURCE CODE TO MODEL:
{source_code}

### VARIABLES YOUR MODEL MUST DECLARE AND UPDATE:
The assertions that will be verified reference exactly these runtime variables.
Your model MUST declare all of them and update them at the appropriate events.
Do NOT declare any other variables beyond these:
{var_hint}

### YOUR TASK:
Produce ONLY variable declarations and process definitions for a PAT3 CSP# model
that captures the concurrent behaviour of the source code.

### STRICT RULES:
- Output ONLY valid .csp variable declarations and process definitions.
- Do NOT output any #define lines. Do NOT output any #assert lines.
- NO comments. NO explanations. NO markdown. NO prose.
- Declare ONLY the variables listed above — do not invent additional variables.
- Variables must be integers: var x = 0;  or  var arr[4] = [0,0,0,0];
- Do NOT use true/false — use 1/0 instead.
- Do NOT use constructor syntax in var declarations (no WaitQueue(), UnsafeCell(), etc.).
- The initialisation event MUST be named 'ini' — NOT 'init'. 'init' is a reserved word in PAT3 and will cause a parse error.
- Use ONLY these operators: ->, [], |||, ;, {{}} for assignments, [guard] for conditionals.
- Variable assignments go inside {{}} blocks on events: event.t{{var = val;}} -> ...
- Conditionals use square brackets before the event: [condition] event.t{{...}} -> ...
- Do NOT use <-, <+, //, =>, or any operator not shown in the reference.
- Every process must end with -> Skip or a recursive call.
- System() must be the last process defined and is the top-level entry point.
"""
    response = CLIENT.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    body = _clean_output(response.choices[0].message.content)
    body = strip_assertions(body)
    body = sanitize_body(body)
    return append_assertions(body, assertions)


def run_pat_check(csp_content):
    """Executes PAT3.Console.exe via Wine and captures results including the result file."""
    temp_file = Path("temp_verify.csp").absolute()
    temp_file.write_text(csp_content, encoding="utf-8")

    print(f"[*] Verifying with PAT3 Console via Wine...")
    try:
        wp_proc = subprocess.run(
            ["winepath", "-w", str(temp_file)],
            capture_output=True, text=True, check=True
        )
        wine_csp_path = wp_proc.stdout.strip()
        wine_out_path = wine_csp_path.replace(".csp", "_result.txt")

        result = subprocess.run(
            ["wine", PAT_EXE_PATH, "-csp", wine_csp_path, wine_out_path],
            capture_output=True, text=True, timeout=60
        )

        output = result.stdout + result.stderr

        # PAT writes errors to the result file, not just stderr
        local_result_file = temp_file.with_name("temp_verify_result.txt")
        if local_result_file.exists():
            output += "\n" + local_result_file.read_text(encoding="utf-8", errors="ignore")

        if "Error" in output or "Exception" in output or "invalid" in output.lower():
            return False, output
        return True, output

    except Exception as e:
        return False, f"Execution Error: {str(e)}"


def repair_model(source_code, current_csp, error_log, assertions):
    """
    Strip assertions from the broken CSP body, send only the body + error log
    to the LLM for repair, then re-append the canonical assertions afterward.
    """
    print(f"[!] PAT found errors. Repairing...")

    scalars, arrays = build_variable_hint(assertions)
    scalar_decls = "\n".join(f"var {v} = 0;" for v in scalars)
    array_decls  = "\n".join(f"var {v}[4] = [0,0,0,0];" for v in arrays)
    var_hint = (scalar_decls + "\n" + array_decls).strip()

    body_only = strip_assertions(current_csp)
    numbered = "\n".join([f"{i+1}: {l}" for i, l in enumerate(body_only.splitlines())])

    prompt = f"""
Fix the PAT CSP# syntax errors shown in the error log below.

### PAT3 SYNTAX REFERENCE (follow this style exactly):
{CSP_SYNTAX_REFERENCE}

### VARIABLES THAT MUST BE DECLARED AND UPDATED IN THE MODEL:
Declare ONLY these variables — do not add or rename any:
{var_hint}

### BROKEN CODE (with line numbers):
{numbered}

### PAT ERROR LOG:
{error_log}

### STRICT RULES:
- Output ONLY corrected variable declarations and process definitions.
- Do NOT output any #define lines. Do NOT output any #assert lines.
- NO comments. NO prose. NO markdown.
- Declare ONLY the variables listed above — do not invent additional variables.
- Variables must be integers: var x = 0; or var arr[4] = [0,0,0,0];
- Do NOT use true/false — use 1/0 instead.
- Do NOT use constructor syntax in var declarations (no WaitQueue(), UnsafeCell(), etc.).
- The initialisation event MUST be named 'ini' — NOT 'init'. 'init' is a reserved word in PAT3 and will cause a parse error.
- Use ONLY operators: ->, [], |||, ;, {{}}, [guard].
- Do NOT use <-, <+, //, or any invented syntax.
- Every process must end with -> Skip or a recursive call.
- System() must be the last process defined.
- KEEP all process definitions from the broken code — do not drop any.
"""
    response = CLIENT.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    body = _clean_output(response.choices[0].message.content)
    body = strip_assertions(body)
    body = sanitize_body(body)
    return append_assertions(body, assertions)


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Automated PAT Model Refiner")
    parser.add_argument("input", help="Source file (e.g. mutex.rs, semaphore.go, channel.c)")
    parser.add_argument("--assertions", help="Manual assertions file", required=True)
    parser.add_argument("--out", default="final_model.csp")
    args = parser.parse_args()

    if not os.path.exists(PAT_EXE_PATH):
        sys.exit(f"ERROR: PAT_EXE_PATH not found at {PAT_EXE_PATH}")

    source_code = Path(args.input).read_text()
    manual_assertions = Path(args.assertions).read_text()

    current_csp = generate_initial_model(source_code, manual_assertions)

    success = False
    for i in range(MAX_REPAIR_LOOPS):
        print(f"\n--- Attempt {i+1} of {MAX_REPAIR_LOOPS} ---")

        # Structural pre-check before invoking PAT (catches obvious failures cheaply)
        struct_ok, reason = validate_structure(current_csp)
        if not struct_ok:
            print(f"[!] Structural pre-check failed: {reason}")
            current_csp = repair_model(source_code, current_csp, reason, manual_assertions)
            continue

        is_valid, log = run_pat_check(current_csp)
        if is_valid:
            print(f"SUCCESS: Model verified.")
            success = True
            break
        else:
            print(f"Error log (first 300 chars):\n{log[:300]}...")
            current_csp = repair_model(source_code, current_csp, log, manual_assertions)

    if not success:
        print(f"\nWARNING: Could not fully verify after {MAX_REPAIR_LOOPS} attempts.")

    Path(args.out).write_text(current_csp, encoding="utf-8")
    print(f"\nResult saved to: {args.out}")


if __name__ == "__main__":
    main()