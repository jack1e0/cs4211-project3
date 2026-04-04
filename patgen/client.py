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

STRICT SYNTAX RULES (MUST FOLLOW EXACTLY):
- Use only CSP# syntax (NOT Event-B, NOT pseudocode)
- Use C-style assignment: = (NEVER :=)
- Use C-style operators: ==, !=, &&, !
- Every state update MUST be inside: event { ... }
- Every transition MUST be: event -> Process
- Every process MUST be recursive (no -> Skip except Init)
- Every guarded process MUST have TWO branches:
    if (cond) { ... } -> P
    [] if (!(cond)) { tau -> P }
- NEVER use undefined functions (no f(x), parity(x), etc.)
- Replace parity(x) with (x % 2)
- Replace sets with integers
- Do NOT use arrays unless explicitly required
- Do NOT use mathematical symbols (∈, ∅, ≠, etc.)

STRUCTURE:
1. #define constants
2. var declarations (all initialized)
3. Init() process
4. One process per Event
5. System() = Init(); (P1() ||| P2() ||| ...)
6. #assert statements

OUTPUT:
- Only valid PAT CSP# code
- No explanations
- No markdown

Output only valid PAT CSP# source code.

Ensure:
- No unreachable processes
- No missing branches in guarded choices
- No deadlocks unless explicitly required
- Consistent naming with the requirements

Example features to include when relevant:
- Lock/Unlock operations
- Queue modeling (bounded if required)
- Thread processes
- Always include safety assertions (mutual exclusion, invariants)
- `#assert System() deadlockfree;`

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


def stage2_system_message(config: Config) -> str:
    return CSP_OUTPUT

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
    resp = client.chat.completions.create(
        model=cfg.model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    choice = resp.choices[0]
    if choice.message.content is None:
        raise RuntimeError("OpenAI returned empty content.")
    return choice.message.content.strip()
