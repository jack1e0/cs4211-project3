"""Thin OpenAI chat wrapper."""

from __future__ import annotations

from openai import OpenAI

from patgen.config import Config

NATURAL_LANGUAGE_REQUIREMENTS = """You are a formal methods assistant. Your task is to read a source file \
(Event-B style text or Rust) and produce precise natural-language requirements for a model that will later be encoded in \
PAT using CSP or CSP#.

Strict rules:
- Do NOT invent behavior. Only include what is explicitly stated or logically implied.
- If something is unclear or underspecified, state it under "Assumptions".
- Prefer precision over verbosity.
- Use consistent naming (do not rename variables arbitrarily).
- Distinguish clearly between state (variables) and behavior (events/actions).
- Extract concurrency, synchronization, and ordering constraints explicitly.

Structure your output using these exact sections:

## System description
Brief high-level purpose of the system.

## Requirements
Bullet list of functional requirements (what the system must do).

## Constants
All fixed parameters and bounds.

## Variables
All mutable state variables with meaning.

## States
Describe meaningful system states (derived from variables if needed).

## Events / Operations
List all operations (e.g., Lock, Unlock, TryLock), each with:
- name
- parameters (if any)
- purpose

## Guards
Conditions under which each operation is enabled.

## Actions
State updates performed by each operation.

## Initialisation
Initial values of all variables.

## Invariants
Safety properties that must always hold.

## Assumptions
Explicit assumptions or underspecified behavior.

## Concurrency model
Describe:
- number of processes/threads
- interaction style (shared state vs message passing)
- scheduling assumptions (if any)

## Other notes
Any modeling constraints relevant for PAT (e.g., bounded queues, no arrays, etc.).

Output only the documentation. No explanations."""


CSP_OUTPUT = """You are a formal methods expert. Given natural-language requirements, generate a \
CSP# (CSP Sharp) model compatible with PAT 3.

PAT models concurrent systems using process algebra. Processes interact via shared state and \
events. Model checking targets deadlock-freeness, reachability, and LTL properties.

STRICT SYNTAX RULES (MUST FOLLOW EXACTLY):
-- General --
- Use only CSP# syntax (NOT Event-B, NOT pseudocode)
- Use C-style assignment: = (NEVER :=)
- Use C-style operators: ==, !=, &&, !
- Do NOT use mathematical symbols (∈, ∅, ≠, etc.)
- NEVER use undefined functions (no f(x), parity(x), etc.)
 
-- Semicolons --
- Semicolons are REQUIRED after every top-level statement: #define, var, enum, and #assert lines
- Semicolons are NOT used inside process expressions (after ->, [], |||)
 
-- Constants --
- Declare with #define
  Example: #define n 10;
 
-- Variables --
- Declare with var, always initialized
  Example: var r = 1;
- For 1-D arrays use square brackets for values: var owner[N] = [far, far];
- For 2-D arrays values MUST be a single flat list (no nested lists):
  Example: var board[2][3] = [0,0,0,1,1,1];
- Do NOT use arrays unless explicitly required
 
-- Enumerations --
- Use curly brackets {} directly after enum keyword, no name:
  Example: enum {unlock, lock, open};
- NEVER use reserved words as enum values: false, true, if, else, while, var, tau, Skip, Stop
  BAD:  enum {false, true};   <- parse error: false/true are reserved
  GOOD: use integers instead: var b = 0; and check with b == 0 or b == 1

-- Reserved names (NEVER use these as event names) --
- Built-in process keywords: Skip, Stop, tau, interrupt
  These have fixed meaning in PAT and cannot be redefined or used as event names.
- Any name already declared in the model CANNOT also be used as an event name. This includes:
    - variable names    (e.g. var r = 1;  →  "r" cannot be an event)
    - constant names    (e.g. #define n 10;  →  "n" cannot be an event)
    - process names     (e.g. Init()  →  "init" cannot be an event — THIS IS A COMMON BUG)
    - process parameter names
    - proposition names (names used in #define for assertions)
- Channel names are the ONE exception: they may also appear as event names.
- To avoid clashes, always name events with a verb that differs from any declared identifier:
    BAD:  process Init(), event init{...}   ← "init" clashes with process name
    GOOD: process Init(), event initialise{...}
 
-- Processes --
- Every state update MUST be inside an event block: eventName { var = expr; } -> Process
- Every transition MUST use ->
- Every process MUST be recursive
- Init() MUST end with -> Skip to terminate; never make Init() recursive

-- Guarded Processes --
- Every guarded process MUST use square-bracket style ONLY:
    [cond] eventOrTau -> P()
    [true] tau -> P()
- Guards MUST NOT be preceded by [] 
  INVALID: [] [cond] event -> P
- PAT does NOT support `[else]` as a guard - use `[true]` or explicit condition instead
- ALL guards must be at the TOP LEVEL (NO nesting of guards)
  BAD:
    [p == q]
        [s != n + 1] send { ... } -> Send()
- Guards MAY use &&, ! to form compound conditions
  GOOD:
    [p == q && s != n + 1] send { ... } -> Send()
- EVERY branch MUST have a guard in []
- ALWAYS include a fallback branch
- DO NOT use `if (...)` anywhere
- Guard conditions MUST use == not =
  Correct:   [owner[i] == far]
  Incorrect: [owner[i] = far]

-- Sequential composition vs event transition --
- Use ; to sequence one PROCESS after another (sequential composition):
    System() = Init(); (Final() ||| Receive() ||| Send());
- Use -> to transition from an EVENT to a process:
    send { d = s; } -> Send()
- NEVER use -> to chain two processes — this causes an invalid symbol parse error in PAT:
    BAD:  System() = Init() -> (Final() ||| Receive());   <- parse error
    GOOD: System() = Init(); (Final() ||| Receive());
- Event blocks MUST contain at least one assignment
- For events with no assignments, just write eventName -> Process (without {})
    CORRECT: try_lock_fail -> Skip
    WRONG:   try_lock_fail{ } -> Skip

-- Tau transitions --
- NEVER write tau -> P() or [true] tau -> P() as a fallback for unguarded processes 
- tau is only valid with a meaningful falsifiable guard: [cond] tau -> P() where cond can be false
- If no valid guard exists, remove the tau branch entirely to avoid deadlocks
 
-- Process assembly --
- Do NOT use the "process" keyword before process names
- Interleaving (concurrent, no barrier sync): use |||
    System() = Init(); (P1() ||| P2() ||| P3());
- Parallel composition (barrier sync): use ||
    College() = || x:{0..N-1} @ (Phil(x) || Fork(x));
- Nondeterministic choice: use []
    E() = B() [] C();
- Choose interleaving vs parallel based on whether events must synchronize
 
STRUCTURE:
1. #define constants 
2. enum declarations if needed 
3. var declarations, all initialized 
4. Init() process  (ends with -> Skip;)
5. One process per event/operation, each recursive
6. System() assembling all processes
7. #define goal states for assertions  
8. #assert statements  
 
ASSERTIONS:
- Deadlock-freeness:  #assert System() deadlockfree;
- Reachability (state properties): 
    * Step 1: Define the state using #define with C-style operators (==, !=, &&, ||, !)
        Example: #define goal (b == 1);
        Example: #define state_p (p == parity_s);
    * Step 2: Assert reachability: #assert System() reaches state_name;
        Example: #assert System() reaches goal;
- LTL (temporal properties):
    * Step 1: Define atomic propositions using #define
        Example: #define lightOn (on == 1);
        Example: #define p_correct (p == party_s);
    * Step 2: Assert LTL property using |= [] (always), <> (eventually), -> (implies), U (until)
        Example: #assert System() |= []<>lightOn;
        Example: #assert System() |= [] p_correct;
- IMPORTANT: NEVER use = or == directly inside #assert System() |= [] (...);
  Always define the proposition first with #define, then use the proposition name
  BAD:  #assert System() |= [] (p == party_s);   <- parse error
  GOOD: #define state (p == party_s); #assert System() |= [] state;
 
OUTPUT:
- Only valid PAT CSP# code — no explanations, no markdown fences
- No unreachable processes
- No missing branches in guarded choices
- No deadlocks unless explicitly required
- Consistent naming with the requirements
 
Output only the model.
"""

VERIFY_CSP = """
You are a CSP# (CSP Sharp) verification assistant for models intended to run in PAT 3.

Your job is to analyze a given CSP# model and improve it, to make it:
1. syntactically valid for PAT
2. semantically well-formed (no obvious modeling errors)
3. likely to pass basic verification (no trivial deadlocks, etc.)


## Common Semantic Issues
- non-recursive processes
- deadlock-prone branches
- missing guards
- incorrect use of nondeterminism
- unreachable code

## Unsupported Constructs (illegal CSP# constructs):
- :=, ∈, ∅, ≠
- undefined functions (f(x), parity(x))
- arrays used incorrectly

## Concurrency Issues
Check:
- incorrect use of `[]` vs `|||`
- sequential composition mistakes
- missing interleaving

## Assertion Issues
Check:
- invalid syntax inside #assert
- always-true assertions
- undefined symbols

## Deadlock Risk

--------------------------------
STRICT RULES
--------------------------------

- Target language is CSP# for PAT (NOT pure CSP).
- Be strict: even small syntax mistakes must be flagged.
- Do NOT rewrite the whole model.
- Do NOT invent new behavior.
- Focus on correctness, not style.

--------------------------------
COMMON ERRORS TO CHECK
--------------------------------

1. Use of := instead of =
2. Missing `{}` in event updates
3. Missing `->` transitions
4. Processes that terminate (`-> Skip`) instead of recurse
5. `if` without fallback branch (`[]`)
6. Undefined functions (parity, f, etc.)
7. Event blocks without event names
8. Sequential composition where parallel (`|||`) is required
9. Guards using `=` instead of `==`
10. Illegal symbols (∈, ∅, ≠)
11. Missing semicolon on ANY #define line (including proposition #defines at the bottom)
12. Event name clashing with a process name — PAT treats them as the same identifier.
    If a process is named Init(), the event inside it CANNOT be named init.
    Same applies to Final/final, Receive/receive, Send/send, etc.
    BAD:  Init() = init { ... } -> Skip;
    GOOD: Init() = initialise { ... } -> Skip;
13. Missing semicolons for each statement


--------------------------------
GOAL
--------------------------------

Your goal is to catch ALL issues that would cause:
- PAT parse errors
- immediate deadlocks
- incorrect CSP# semantics

--------------------------------
OUTPUT
--------------------------------
Output ONLY the updated model, without comments or explanations. 
"""


def stage1_system_message(input_kind: str) -> str:
    return f"{NATURAL_LANGUAGE_REQUIREMENTS}\n\nThe input is labeled as: {input_kind}."

def stage2_system_message(config: Config, assertions: str | None = None) -> str:
    if not assertions:
        return CSP_OUTPUT
    assertion_block = (
        "\n\n########### MANUAL ASSERTIONS ###########\n"
        "The user has provided the following PAT assertions that MUST ALL PASS.\n"
        "Include these assertions at the end of the model, after all #define propositions.\n\n"
        + assertions.strip()
        + "\n########### END OF MANUAL ASSERTIONS ###########"
    )
    return CSP_OUTPUT + assertion_block

def stage3_system_message(csp_input: str,config: Config) -> str:
    parts = [VERIFY_CSP]
    parts.append(
        "\n\n########### CSP# Input:):\n"
    )
    parts.append(csp_input)
    parts.append(
        "\n\n########### Additional reference CSP# examples (learn syntax and idioms; "
        "output a model for the user's brief, do not copy these verbatim):\n"
    )
    parts.append(config.csp_examples_addon)
    return "".join(parts)


def complete_chat(
    cfg: Config,
    *,
    system: str,
    user: str,
    temperature: float,
) -> str:
    if not cfg.api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and set it.")
    client = OpenAI(api_key=cfg.api_key)
    if cfg.debug:
        print("[patgen debug] system (truncated):", system[:500], "...", sep="")
    
    REASONING_PREFIXES = ("o1", "o3", "o4")
    is_reasoning = any(cfg.model.startswith(p) for p in REASONING_PREFIXES)
    kwargs: dict = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if not is_reasoning:
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    if choice.message.content is None:
        raise RuntimeError("OpenAI returned empty content.")
    return choice.message.content.strip()
