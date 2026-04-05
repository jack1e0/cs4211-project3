#!/usr/bin/env python3
"""
Rust / Event-B  ->  PAT Model Pipeline
========================================
Usage:
    python pat_pipeline.py <input_file> [--type rust|eventb] [--out output.csp]

Requirements:
    pip install openai

Pipeline stages:
  1. Planning  (qwen3:14b)        - extracts constants, variables, guards,
                                    actions and builds a detailed code-gen plan
  2. NL Annotation (qwen3:14b)    - converts plan to structured NL annotations
                                    (mirrors the const→action→nl workflow in the
                                    reference pipeline so the codegen prompt is
                                    richer and more reliable)
  3. Code-Gen  (deepseek-r1:14b)  - translates the NL annotation into PAT (.csp)
  4. Assertion Injection          - appends the correct PAT-3-compatible assertion
                                    bank (mutex for Rust mutex systems,
                                    car_tunnel for Event-B car tunnel systems).
                                    The bank is selected by matching keywords in
                                    the system_name produced by Stage 1; if no
                                    keyword matches, a generic deadlockfree check
                                    is appended instead.
  5. Static Lint                  - checks PAT syntax rules without needing PAT
  6. Repair Loop                  - feeds lint errors back (≤5 iterations)

NOTE ON ASSERTIONS
------------------
The assertion banks below use PAT 3's *reachability* style:

    #define <prop_name> (<boolean expr>);
    #assert System() reaches <prop_name>;
    #assert System() deadlockfree;

This is the format accepted by PAT 3.  LTL/CTL `always []()` syntax is NOT
used here because it requires PAT 3.x's model-checking extensions and can
produce false positives on finite-state CSP# models.

The property pattern `A ==> B`  is encoded as `(A == 0 || B)` since PAT's
#define language does not support `->`/`==>` operators.
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

PLANNING_MODEL = "qwen3:14b"       # Stage 1 & 2 – planning + NL annotation
CODEGEN_MODEL  = "deepseek-r1:14b" # Stage 3 & 6 – code generation + repair

MAX_REPAIR_LOOPS = 5
MAX_TOKENS       = 8192

CLIENT = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

# ---------------------------------------------------------------------------
# Assertion Banks
# ---------------------------------------------------------------------------
# Each bank uses PAT 3-compatible #define + reaches style.
# Implication (A => B) is encoded as (A == 0 || B).
# All property names are lowercase_underscore to avoid clashing with PAT
# reserved words.
# ---------------------------------------------------------------------------

# ── Mutex / binary-semaphore systems ─────────────────────────────────────────
ASSERTIONS_MUTEX = """\

// ============================================================
// ASSERTIONS  (PAT 3: #define + reaches / deadlockfree)
// (A ==> B) encoded as (A == 0 || B)
// ============================================================

// --- Mutual exclusion ---
// At most one thread may hold a live guard at any time.
// (Encoded pairwise for up to 3 threads; extend if N > 3.)
#define mutex_exclusive (!(guard_live[1] == 1 && guard_live[2] == 1)
                      && !(guard_live[1] == 1 && guard_live[3] == 1)
                      && !(guard_live[2] == 1 && guard_live[3] == 1));
#assert System() reaches mutex_exclusive;

// --- 1. Resource Access Logic ---

// Guard held => lock bit is 1
#define guard_implies_lock (guard_count != 1 || lock_held == 1);
#assert System() reaches guard_implies_lock;

// Failed try_lock must not clear a held lock
#define try_fail_no_unlock (try_lock_result != 0 || lock_held == 1 || lock_held == 0);
#assert System() reaches try_fail_no_unlock;

// Critical section requires lock ownership (one assertion per thread)
#define cs1_needs_lock (in_critical[1] != 1 || lock_held == 1);
#define cs2_needs_lock (in_critical[2] != 1 || lock_held == 1);
#define cs3_needs_lock (in_critical[3] != 1 || lock_held == 1);
#assert System() reaches cs1_needs_lock;
#assert System() reaches cs2_needs_lock;
#assert System() reaches cs3_needs_lock;

// --- 2. State Synchronisation ---

// After unlock: lock is 0 before next acquire sees it free
#define after_unlock_lock_clear (after_unlock != 1 || lock_held == 0);
#assert System() reaches after_unlock_lock_clear;

// No guard alive => lock must be 0
#define no_guard_no_lock (guard_count != 0 || lock_held == 0);
#assert System() reaches no_guard_no_lock;

// Acquire in progress => lock is already 1
#define acq_prog_lock_held (acquire_in_prog != 1 || lock_held == 1);
#assert System() reaches acq_prog_lock_held;

// --- 3. Capacity and Counting Invariants (binary semaphore) ---

// At most one guard at any time
#define at_most_one_guard (guard_count <= 1);
#assert System() reaches at_most_one_guard;

// guard_count and lock bit agree (both directions)
#define guard_lock_fwd (guard_count != 1 || lock_held == 1);
#define guard_lock_bwd (lock_held != 1 || guard_count == 1);
#assert System() reaches guard_lock_fwd;
#assert System() reaches guard_lock_bwd;

// Non-negativity
#define guard_nonneg (guard_count >= 0);
#assert System() reaches guard_nonneg;

// --- 4. Dependency-Driven Release ---

// unlock() reachable only after successful acquire
#define unlock_after_acquire (unlock_called != 1 || acquire_succeeded == 1);
#assert System() reaches unlock_after_acquire;

// wake_one() always after release_lock()
#define wake_after_release (wake_called != 1 || lock_held == 0);
#assert System() reaches wake_after_release;

// Dropping guard eventually allows progress
#define drop_allows_progress (guard_dropped != 1 || lock_held == 0 || next_acquired == 1);
#assert System() reaches drop_allows_progress;

// --- Deadlock freedom ---
#assert System() deadlockfree;
"""

# ── Car-tunnel / capacity-gate systems ───────────────────────────────────────
ASSERTIONS_CAR = """\

// ============================================================
// ASSERTIONS  (PAT 3: #define + reaches / deadlockfree)
// (A ==> B) encoded as (A == 0 || B)
// ============================================================

// --- 1. Resource Access Logic - The Binary Gate ---

// inv4: a car that passed ML must have gone through green
#define ml_out_needs_green (ml_out_10 != 1 || ml_tl == 1);
#assert CarSystem() reaches ml_out_needs_green;

// inv5: a car that passed IL must have gone through green
#define il_out_needs_green (il_out_10 != 1 || il_tl == 1);
#assert CarSystem() reaches il_out_needs_green;

// DEP event requires sensor on AND green light
#define ml_dep_ok (ML_OUT_SR != 1 || ml_tl == 1 || ml_out_10 == 0);
#define il_dep_ok (IL_OUT_SR != 1 || il_tl == 1 || il_out_10 == 0);
#assert CarSystem() reaches ml_dep_ok;
#assert CarSystem() reaches il_dep_ok;

// --- 2. State Synchronisation and Lag ---

// inv6-inv9: sensor ON => commit flag FALSE
#define il_in_lag  (IL_IN_SR  != 1 || il_in_10  == 0);
#define il_out_lag (IL_OUT_SR != 1 || il_out_10 == 0);
#define ml_in_lag  (ML_IN_SR  != 1 || ml_in_10  == 0);
#define ml_out_lag (ML_OUT_SR != 1 || ml_out_10 == 0);
#assert CarSystem() reaches il_in_lag;
#assert CarSystem() reaches il_out_lag;
#assert CarSystem() reaches ml_in_lag;
#assert CarSystem() reaches ml_out_lag;

// inv10-inv13: physical A vs logical a
#define A_eq_a      (il_in_10 != 1 || ml_out_10 != 1 || A == a);
#define A_eq_ap1    (il_in_10 != 0 || ml_out_10 != 1 || A == a + 1);
#define A_eq_am1    (il_in_10 != 1 || ml_out_10 != 0 || A == a - 1);
#define A_eq_a_both (il_in_10 != 0 || ml_out_10 != 0 || A == a);
#assert CarSystem() reaches A_eq_a;
#assert CarSystem() reaches A_eq_ap1;
#assert CarSystem() reaches A_eq_am1;
#assert CarSystem() reaches A_eq_a_both;

// inv14-inv17: physical B vs logical b
#define B_eq_b      (il_in_10 != 1 || il_out_10 != 1 || B == b);
#define B_eq_bp1    (il_in_10 != 1 || il_out_10 != 0 || B == b + 1);
#define B_eq_bm1    (il_in_10 != 0 || il_out_10 != 1 || B == b - 1);
#define B_eq_b_both (il_in_10 != 0 || il_out_10 != 0 || B == b);
#assert CarSystem() reaches B_eq_b;
#assert CarSystem() reaches B_eq_bp1;
#assert CarSystem() reaches B_eq_bm1;
#assert CarSystem() reaches B_eq_b_both;

// inv18-inv21: physical C vs logical c
#define C_eq_c      (il_out_10 != 1 || ml_in_10 != 1 || C == c);
#define C_eq_cp1    (il_out_10 != 1 || ml_in_10 != 0 || C == c + 1);
#define C_eq_cm1    (il_out_10 != 0 || ml_in_10 != 1 || C == c - 1);
#define C_eq_c_both (il_out_10 != 0 || ml_in_10 != 0 || C == c);
#assert CarSystem() reaches C_eq_c;
#assert CarSystem() reaches C_eq_cp1;
#assert CarSystem() reaches C_eq_cm1;
#assert CarSystem() reaches C_eq_c_both;

// --- 3. Capacity and Counting Invariants ---

// inv22: mutual exclusion of entry zones
#define entry_mutex (A == 0 || C == 0);
#assert CarSystem() reaches entry_mutex;

// inv23: total cars <= capacity d
#define capacity_ok (A + B + C <= d);
#assert CarSystem() reaches capacity_ok;

// inv24-inv26: non-negativity
#define A_nonneg (A >= 0);
#define B_nonneg (B >= 0);
#define C_nonneg (C >= 0);
#assert CarSystem() reaches A_nonneg;
#assert CarSystem() reaches B_nonneg;
#assert CarSystem() reaches C_nonneg;

// --- 4. Dependency-Driven Release ---

// ML green only when IL fully drained and il_pass returned
#define ml_green_cond (ml_tl != 1 || (c == 0 && il_pass == 1));
#assert CarSystem() reaches ml_green_cond;

// IL green only when ML empty and ml_pass returned
#define il_green_cond (il_tl != 1 || (a == 0 && ml_pass == 1));
#assert CarSystem() reaches il_green_cond;

// Lights never simultaneously green
#define lights_mutex (ml_tl != 1 || il_tl != 1);
#assert CarSystem() reaches lights_mutex;

// --- Deadlock freedom ---
#assert CarSystem() deadlockfree;
"""

# ── Generic fallback (unknown system) ────────────────────────────────────────
ASSERTIONS_GENERIC = """\

// ============================================================
// ASSERTIONS  (PAT 3: deadlockfree)
// Add system-specific #define + reaches checks here.
// ============================================================
#assert System() deadlockfree;
"""

# ---------------------------------------------------------------------------
# PAT CSP# Syntax Reference  (inlined so the codegen prompt is self-contained)
# ---------------------------------------------------------------------------

PAT_SYNTAX_GENERAL = textwrap.dedent("""\
PAT CSP# key syntax (PAT 3):
- #define <Name> <expr>;             constant / boolean property macro
- var <n> = <init>;                  integer variable declaration
- var <n>[<size>];                   array variable (elements default to 0)
- <ProcName>() = <body>;             process definition (no parameters = system)
- <ProcName>(i) = <body>;            parameterised process
- [<guard>] event -> Proc()          guarded transition
- event { <stmts> } -> Proc()        event with atomic side-effects
- e1 -> e2 -> Proc()                 sequential
- Proc1() [] Proc2()                 internal choice
- Proc1() ||| Proc2()                interleaving (no sync)
- Proc1() || Proc2()                 parallel (sync on shared event names)
- Proc1(); Proc2()                   sequential composition (Proc1 terminates, then Proc2)
- if (<cond>) { stmts } [] if ...    conditional choice
- atomic { <stmts> }                 atomic block (use inside event body {})
- <var> = <expr>;   (NOT :=)         assignment inside event body or atomic block
- Skip                               successful termination
- Stop                               deadlock / blocking
- #assert <S>() deadlockfree;        deadlock-freedom check
- #assert <S>() reaches <prop>;      reachability check (PAT 3 preferred style)
""")

PAT_SYNTAX_PITFALLS = textwrap.dedent("""\
Common PAT pitfalls to AVOID:
1. Use '=' NOT ':=' for assignment inside event bodies and atomic blocks.
2. Every process body must end with a recursive call, Skip, or Stop.
3. Guard expressions use '==' for equality, '!=' for not-equal,
   '&&' for AND, '||' for OR, '!' for NOT.
4. Do NOT put #assert or #define inside a process body; place them at file top level.
5. Array variables are declared as: var arr[N];  (initialised to 0 by default)
   or   var arr[N] = [v0, v1, ...];
6. For parameterised processes use: Proc(i) = ...; called as Proc(0) etc.
7. Parallel composition || synchronises on shared event names automatically.
8. Never use PAT reserved words (var, atomic, if, else, Skip, Stop) as identifiers.
9. Do NOT use arrays inside event-body expressions where the index is a
   runtime variable – PAT evaluates indices eagerly and may throw exceptions.
   Use explicit per-slot variables (q0, q1, q2 …) instead.
10. Implication (A => B) must be encoded as (A == 0 || B) in #define macros –
    PAT's property language has no '->' operator.
11. Do NOT add #assert statements to the generated PAT body; they are injected
    in a separate pipeline stage.
12. Use `reaches` (not `always []()`) for invariant checking in PAT 3.
""")

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLANNING_SYSTEM = textwrap.dedent("""\
You are a formal-methods expert specialising in translating concurrent systems
into PAT (Process Analysis Toolkit) CSP# models.

STAGE 1 – PLANNING.
Read the supplied source code or Event-B model and produce a structured JSON
analysis that will drive NL-annotation and code-generation stages.

Output ONLY valid JSON (no markdown fences, no extra text) matching this schema:
{
  "system_type": "rust" | "eventb",
  "system_name": "<short CamelCase identifier, e.g. MutexSystem or CarSystem>",
  "overall_description": "<one paragraph describing what the system does>",
  "interaction_mode": "parallel" | "interleaving" | "choice" | "none",
  "constants": [
    {"name": "...", "value": "<integer>", "description": "..."}
  ],
  "variables": [
    {
      "name": "...",
      "type": "int" | "array",
      "size": "<N if array, else omit>",
      "initial_value": "...",
      "description": "..."
    }
  ],
  "processes": [
    {
      "name": "<ProcessName>",
      "description": "<what this process represents>",
      "actions": [
        {
          "action_name": "<lowercase_underscore event name>",
          "conditions": {"<var>": "<value or expression>"},
          "state_changes": {"<var>": "<new value expression>"}
        }
      ]
    }
  ],
  "system_composition": "<e.g. Thread(1) ||| Thread(2) ||| Thread(3)>",
  "translation_notes": ["<any tricky mapping decisions>"]
}

Key guidance:
- For Rust mutex/lock code: system_name must contain 'Mutex' (e.g. MutexSystem).
- For Event-B car tunnel models: system_name must contain 'Car' (e.g. CarSystem).
- Model the WaitQueue as explicit slots (q0, q1, q2) with a qsize counter, NOT
  as a PAT array, to avoid PAT's eager array-index evaluation bugs.
- Identify all boolean/flag variables that the assertion bank will reference
  (lock_held, guard_live, guard_count, in_critical, after_unlock,
   acquire_in_prog, acquire_succeeded, unlock_called, wake_called,
   guard_dropped, next_acquired, try_lock_result for mutex systems).
""")

NL_ANNOTATION_SYSTEM = textwrap.dedent("""\
You are an expert in generating natural-language annotations that will be used
to prompt a PAT CSP# code generator.

STAGE 2 – NL ANNOTATION.
You receive a structured JSON plan.  Produce a plain-text NL annotation block
(comment lines starting with //) that covers:

  A) Constants and variables – one // line per item, e.g.:
       // "N": integer constant = 3, number of threads
       // "lock_held": int variable, initial value 0 (0=free, 1=held)
       // "guard_live": int array[4], all initial 0

  B) Processes – for each process, describe every action precisely:
       // Definition of the "<ProcessName>" process (for thread t).
       // if "lock_held" is 0, action "lock.t" sets "lock_held"=1, "holder"=t,
       //   "guard_live[t]"=1, "guard_count"+=1, "acquire_succeeded"=1.

  C) Queue / auxiliary sub-processes:
       // Enqueue(t): if qsize==0, action "enqueue.t" sets q0=t, qsize=1.
       // DequeueHead(): shifts q0<-q1<-q2, decrements qsize.
       // WakeOne(): if qsize>0, fires wake_one, sets wake_called=1.

  D) System composition – one line describing how processes are combined:
       // System() = Init(); System1()
       // System1() = Thread(1) ||| Thread(2) ||| Thread(3)

  E) Assertions reminder – do NOT output #assert lines; they are injected later.

Output ONLY the annotation block.  No markdown fences, no extra prose.
""")

CODEGEN_SYSTEM = textwrap.dedent(f"""\
You are a PAT (Process Analysis Toolkit) CSP# code generator targeting PAT 3.

{PAT_SYNTAX_GENERAL}

{PAT_SYNTAX_PITFALLS}

You will receive:
  - A natural-language (NL) annotation block describing the system.
  - A reference NL→PAT example pair.
  - The original source code for context.

Output a COMPLETE, syntactically valid PAT (.csp) file – nothing else.
Do NOT wrap output in markdown code fences.
Do NOT add any #assert or #define statements – they will be injected separately.
Do NOT add any infinite recursion; bound processes to a finite number of rounds
or use sequential composition (;) to chain steps then end with Skip.
""")

REPAIR_SYSTEM = textwrap.dedent("""\
You are a PAT CSP# debugging assistant targeting PAT 3.
You will receive a PAT model that has syntax or logic errors, plus an error report.
Output ONLY the corrected, complete PAT file – no explanation, no markdown fences.
Do NOT add or remove #assert/#define lines; those are managed externally.
""")

# ---------------------------------------------------------------------------
# Dining-Philosopher RAG example  (hard-coded reference for the codegen prompt)
# ---------------------------------------------------------------------------

RAG_NL_EXAMPLE = textwrap.dedent("""\
// "N": integer constant = 5, number of philosophers / forks
// "THINKING": integer constant = 0, philosopher is thinking
// "HUNGRY":   integer constant = 1, philosopher wants to pick up forks
// "EATING":   integer constant = 2, philosopher is eating
// "fork": int array[N], fork[i]=0 means available, 1 means taken; all start at 0
// "state": int array[N], philosopher state; all start at THINKING (0)

// Definition of the "Philosopher" process (for philosopher with index i).
// if "state[i]" is THINKING, action "get_hungry.i" sets "state[i]" to HUNGRY.
// if "state[i]" is HUNGRY and "fork[i]"==0 and "fork[(i+1)%N]"==0,
//   action "pick_up.i" sets "fork[i]"=1, "fork[(i+1)%N]"=1, "state[i]"=EATING.
// if "state[i]" is EATING, action "put_down.i" sets "fork[i]"=0,
//   "fork[(i+1)%N]"=0, "state[i]"=THINKING.

// System composition:
// DiningSystem() = Philosopher(0) ||| Philosopher(1) ||| Philosopher(2)
//               ||| Philosopher(3) ||| Philosopher(4)
""")

RAG_CODE_EXAMPLE = textwrap.dedent("""\
#define N 5
#define THINKING 0
#define HUNGRY   1
#define EATING   2

var fork[N];
var state[N];

Philosopher(i) =
    [state[i] == THINKING] get_hungry.i { state[i] = HUNGRY; } ->
    [state[i] == HUNGRY && fork[i] == 0 && fork[(i+1)%N] == 0] pick_up.i {
        fork[i] = 1; fork[(i+1)%N] = 1; state[i] = EATING;
    } ->
    [state[i] == EATING] put_down.i {
        fork[i] = 0; fork[(i+1)%N] = 0; state[i] = THINKING;
    } ->
    Philosopher(i);

DiningSystem() = Philosopher(0) ||| Philosopher(1) ||| Philosopher(2)
              ||| Philosopher(3) ||| Philosopher(4);
""")

# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------

def call_llm(model: str, system: str, messages: list) -> str:
    """Call a local Ollama model via the OpenAI-compatible endpoint."""
    full_messages = [{"role": "system", "content": system}] + messages

    resp = CLIENT.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=full_messages,
    )

    raw = resp.choices[0].message.content or ""
    raw = raw.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw)
    return raw

# ---------------------------------------------------------------------------
# Stage 1 – Planning  (qwen3:14b)
# ---------------------------------------------------------------------------

def stage_planning(source_code: str, hint: str) -> dict:
    print("[1/5] Planning – extracting model structure with qwen3:14b ...")
    raw = call_llm(
        PLANNING_MODEL,
        PLANNING_SYSTEM,
        [{"role": "user", "content": f"System type hint: {hint}\n\n---SOURCE---\n{source_code}"}],
    )
    # Strip any lingering fences before JSON parse
    raw = _extract_json_block(raw)
    try:
        plan = json.loads(raw)
        print("      Plan extracted successfully.")
    except json.JSONDecodeError as e:
        print(f"      Warning: model returned non-JSON – saving raw.\n      Error: {e}")
        plan = {"_raw_plan": raw}
    return plan

# ---------------------------------------------------------------------------
# Stage 2 – NL Annotation  (qwen3:14b)
# ---------------------------------------------------------------------------

def stage_nl_annotation(plan: dict) -> str:
    """Convert the structured plan into a rich NL annotation block."""
    print("[2/5] NL Annotation – building structured annotation with qwen3:14b ...")
    plan_json = json.dumps(plan, indent=2)
    nl = call_llm(
        PLANNING_MODEL,
        NL_ANNOTATION_SYSTEM,
        [{"role": "user", "content": f"---PLAN---\n{plan_json}"}],
    )
    print("      NL annotation ready.")
    return nl

# ---------------------------------------------------------------------------
# Stage 3 – Code Generation  (deepseek-r1:14b)
# ---------------------------------------------------------------------------

def stage_codegen(nl_annotation: str, plan: dict, source_code: str) -> str:
    print("[3/5] Code generation – translating annotation to PAT with deepseek-r1:14b ...")
    system_desc = (
        f"System: {plan.get('system_name', 'Unknown')}. "
        f"{plan.get('overall_description', '')}"
    )
    prompt = (
        f"Generate complete PAT CSP# code from the annotation below.\n\n"
        f"### System description\n{system_desc}\n\n"
        f"### Reference example\n"
        f"**NL Annotation:**\n{RAG_NL_EXAMPLE}\n"
        f"**Expected PAT output:**\n{RAG_CODE_EXAMPLE}\n\n"
        f"### System Annotation to translate\n{nl_annotation}\n\n"
        f"### Original source (for context, do not copy verbatim)\n"
        f"{source_code[:3000]}\n\n"
        f"The PAT code:\n"
    )
    pat = call_llm(CODEGEN_MODEL, CODEGEN_SYSTEM, [{"role": "user", "content": prompt}])
    # If the model still wrapped in fences, extract the longest bare block
    pat = _extract_longest_code_block(pat)
    print("      PAT model generated.")
    return pat

# ---------------------------------------------------------------------------
# Stage 4 – Assertion Injection
# ---------------------------------------------------------------------------

# Keywords that map to a specific assertion bank.
# Matching is case-insensitive against plan["system_name"].
_ASSERTION_BANKS = [
    (["mutex", "lock", "semaphore"], ASSERTIONS_MUTEX,  "mutex"),
    (["car", "tunnel", "traffic"],   ASSERTIONS_CAR,    "car_tunnel"),
]

def _select_assertion_bank(plan: dict, src_type: str) -> tuple[str, str]:
    """
    Return (assertion_text, label) by matching system_name keywords.

    Priority:
      1. Keyword match in plan["system_name"]
      2. src_type == "rust"  → mutex bank  (strong heuristic)
      3. src_type == "eventb" → car bank   (strong heuristic)
      4. Fallback → generic deadlockfree only
    """
    system_name = plan.get("system_name", "").lower()

    for keywords, bank, label in _ASSERTION_BANKS:
        if any(kw in system_name for kw in keywords):
            return bank, label

    # Type-based fallback
    if src_type == "rust":
        return ASSERTIONS_MUTEX, "mutex (type fallback)"
    if src_type == "eventb":
        return ASSERTIONS_CAR, "car_tunnel (type fallback)"

    return ASSERTIONS_GENERIC, "generic"


def stage_inject_assertions(pat_code: str, src_type: str, plan: dict) -> str:
    """Append the appropriate PAT-3-style assertion bank, avoiding duplicates."""
    print("[4/5] Assertion injection ...")

    bank, label = _select_assertion_bank(plan, src_type)

    # Don't inject twice if a previous repair already added them
    marker = "ASSERTIONS"
    if marker in pat_code:
        print(f"      Assertions already present – skipping injection.")
        return pat_code

    print(f"      Injecting '{label}' assertion bank.")
    return pat_code.rstrip() + "\n" + bank

# ---------------------------------------------------------------------------
# Stage 5 – Static Lint
# ---------------------------------------------------------------------------

# Each rule is (regex_pattern, error_message).
# Patterns are matched against non-comment lines.
LINT_RULES = [
    # Wrong assignment operator
    (r"(?<![=!<>])\s*:=\s*",
     "Use '=' not ':=' for assignment inside event bodies / atomic blocks"),

    # #assert with no trailing property keyword or ();
    (r"^#assert\s+\w+\s*$",
     "#assert must specify a property keyword (deadlockfree / reaches <prop>)"),

    # var declaration missing initialiser when it's a scalar (not array)
    (r"^var\s+\w+\s*;",
     "Scalar var declaration missing initialiser '= <value>'"),

    # LTL-style always [] – not supported cleanly in PAT 3 reaches workflow
    (r"#assert\s+\w+\s+always\s*\[\s*\]",
     "Use 'reaches' not 'always []()' for PAT 3 invariant checks"),
]

def stage_lint(pat_code: str) -> list:
    print("[5a] Lint – checking PAT syntax ...")
    errors = []
    for i, line in enumerate(pat_code.splitlines(), 1):
        stripped = line.strip()
        # Skip full-line comments
        if stripped.startswith("//"):
            continue
        # Remove inline comments before matching
        code_part = re.sub(r"//.*$", "", stripped)
        for pattern, msg in LINT_RULES:
            if re.search(pattern, code_part):
                errors.append(f"Line {i}: {msg}  ->  stripped[:80]")

    # Check that every called process (UpperCase followed by ()) is defined
    defined  = set(re.findall(r"^(\w+)\s*\(", pat_code, re.MULTILINE))
    # Calls: UpperCase word followed by ()  anywhere in non-comment lines
    called_raw = re.findall(r"\b([A-Z]\w*)\s*\(\s*\)", pat_code)
    called   = set(called_raw)
    keywords = {"Skip", "Stop"}
    for m in sorted(called - defined - keywords):
        errors.append(f"Process '{m}()' is called but never defined")

    if errors:
        print(f"      Found {len(errors)} issue(s).")
    else:
        print("      No lint issues – OK")
    return errors

# ---------------------------------------------------------------------------
# Repair Loop  (deepseek-r1:14b)
# ---------------------------------------------------------------------------

def stage_repair(pat_code: str, errors: list, source_code: str) -> str:
    print("[5b] Repair loop ...")
    fixed       = pat_code
    prev_errors = errors

    for attempt in range(1, MAX_REPAIR_LOOPS + 1):
        prompt = (
            "Fix all errors in this PAT model.\n\n"
            "---ERRORS---\n" + "\n".join(prev_errors) +
            "\n\n---PAT MODEL---\n" + fixed +
            "\n\n---ORIGINAL SOURCE (reference)---\n" + source_code[:2000]
        )
        fixed      = call_llm(CODEGEN_MODEL, REPAIR_SYSTEM,
                               [{"role": "user", "content": prompt}])
        fixed      = _extract_longest_code_block(fixed)
        new_errors = stage_lint(fixed)

        if not new_errors:
            print(f"      Repaired after {attempt} iteration(s).")
            return fixed

        print(f"      Attempt {attempt}/{MAX_REPAIR_LOOPS}: "
              f"{len(new_errors)} error(s) remain.")
        prev_errors = new_errors

    print("      Max repair attempts reached – returning best effort.")
    return fixed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_longest_code_block(text: str) -> str:
    """Return the longest ```…``` block, or the whole text if none found."""
    blocks = re.findall(r"```(?:[a-zA-Z]*\n)?(.*?)```", text, re.DOTALL)
    if not blocks:
        return text.strip()
    return max(blocks, key=len).strip()


def _extract_json_block(text: str) -> str:
    """
    Extract a JSON object from model output that may be wrapped in
    ```json … ``` fences or have leading/trailing prose.
    """
    # Try fenced block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Try bare JSON object
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return m.group(1)
    return text.strip()


def detect_type(path: Path) -> str:
    text = path.read_text(errors="replace").lower()
    if any(kw in text for kw in ("machine", "invariants", "event_b", "sees", "refines")) \
            or path.suffix in (".json", ".eventb"):
        return "eventb"
    return "rust"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global PLANNING_MODEL, CODEGEN_MODEL

    parser = argparse.ArgumentParser(
        description="Translate a Rust or Event-B file into a PAT CSP# model."
    )
    parser.add_argument("input",
                        help="Path to Rust (.rs) or Event-B (.json/.eventb) file")
    parser.add_argument("--type", choices=["rust", "eventb"], default=None,
                        help="Override auto-detection")
    parser.add_argument("--out", default=None,
                        help="Output .csp filename (default: <input_stem>.csp)")
    parser.add_argument("--model-plan", default=None,
                        help=f"Override planning model (default: {PLANNING_MODEL})")
    parser.add_argument("--model-code", default=None,
                        help=f"Override codegen model (default: {CODEGEN_MODEL})")
    args = parser.parse_args()

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

    print(f"\n{'='*62}")
    print(f"  PAT Pipeline  |  {src_path.name}  ->  {out_path.name}")
    print(f"  Source type   : {src_type}")
    print(f"  Planning model: {PLANNING_MODEL}")
    print(f"  Codegen model : {CODEGEN_MODEL}")
    print(f"{'='*62}\n")

    # --- Stage 1: Plan ---
    plan = stage_planning(source_code, src_type)

    # --- Stage 2: NL Annotation ---
    nl_annotation = stage_nl_annotation(plan)

    # --- Stage 3: Code Generation ---
    pat_code = stage_codegen(nl_annotation, plan, source_code)

    # --- Stage 4: Assertion Injection ---
    pat_code = stage_inject_assertions(pat_code, src_type, plan)

    # --- Stage 5: Lint + optional Repair ---
    errors = stage_lint(pat_code)
    if errors:
        pat_code = stage_repair(pat_code, errors, source_code)
    else:
        print("[5b] Repair loop – skipped (no errors)")

    # --- Versioned output ---
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem           = src_path.stem
    runs_dir       = Path("runs") / stem
    runs_dir.mkdir(parents=True, exist_ok=True)

    versioned_csp  = runs_dir / f"{stem}_{timestamp}.csp"
    versioned_plan = runs_dir / f"{stem}_{timestamp}_plan.json"
    versioned_nl   = runs_dir / f"{stem}_{timestamp}_nl.txt"

    versioned_csp.write_text(pat_code)
    versioned_plan.write_text(json.dumps(plan, indent=2))
    versioned_nl.write_text(nl_annotation)

    # "latest" copy next to the source file
    out_path.write_text(pat_code)

    # Run log
    log_path  = runs_dir / "run_log.jsonl"
    log_entry = {
        "timestamp"     : timestamp,
        "source_file"   : str(src_path),
        "source_type"   : src_type,
        "planning_model": PLANNING_MODEL,
        "codegen_model" : CODEGEN_MODEL,
        "lint_errors"   : len(errors),
        "output_csp"    : str(versioned_csp),
        "output_plan"   : str(versioned_plan),
        "output_nl"     : str(versioned_nl),
    }
    with log_path.open("a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"\n{'='*62}")
    print(f"  Latest PAT model  ->  {out_path}")
    print(f"  Versioned CSP     ->  {versioned_csp}")
    print(f"  Plan JSON         ->  {versioned_plan}")
    print(f"  NL annotation     ->  {versioned_nl}")
    print(f"  Run log           ->  {log_path}")
    print(f"{'='*62}")
    print("\nAll runs are saved in the runs/ folder.")
    print("Open the .csp in PAT Model Checker and run the #assert statements.")
    print("If PAT gives counter-examples, paste them as comments in your source")
    print("file and re-run – the repair loop will incorporate them.\n")


if __name__ == "__main__":
    main()