"""Orchestrate Stage 1 (NL brief) → Stage 2 (PAT-style text)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from patgen.client import (
    complete_chat,
    stage1_system_message,
    stage2_system_message,
    stage3_system_message,  
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

    # brief = complete_chat(
    #     cfg,
    #     system=stage1_system_message(input_kind),
    #     user=user1,
    #     temperature=cfg.temperature_stage1,
    # )
    brief = """
    ## System description
The system manages a communication mechanism where data is sent and received based on the parity of certain state variables.

## Requirements
- The system must initialize state variables to specific values.
- The system must allow sending data when certain conditions on parity and state variables are met.
- The system must allow receiving data when the parity of two state variables differs.
- The system must track whether a final condition has been reached.

## Constants
- `parity`: A function mapping natural numbers to integers.

## Variables
- `h`: A collection (e.g., array or map) to hold received data.
- `r`: A counter for received messages, initialized to 1.
- `s`: A counter for sent messages, initialized to 1.
- `d`: A variable representing the data to be sent or received.
- `p`: A variable representing the parity of `s`.
- `q`: A variable representing the parity of `r`.
- `b`: A boolean flag indicating whether the final condition has been reached.

## States
- The system can be in a state where `b` is `TRUE` (final condition reached) or `FALSE` (final condition not reached).
- The values of `p` and `q` reflect the parity of `s` and `r`, respectively.

## Events / Operations
- **INITIALISATION**
  - Purpose: Set initial values for all state variables.
  
- **final**
  - Purpose: Set the final condition flag to `TRUE` when certain conditions are met.
  
- **receive**
  - Purpose: Store received data and update counters when the parity of `p` and `q` differs.
  
- **send**
  - Purpose: Send data and update counters when the parity of `p` and `q` is the same and other conditions are satisfied.

## Guards
- **INITIALISATION**: No guards.
- **final**: Enabled when `r = n + 1` and `b = FALSE`.
- **receive**: Enabled when `p ≠ q`.
- **send**: Enabled when `p = q`, `s ≠ n + 1`, `p = parity(s)`, and `q = parity(r)`.

## Actions
- **INITIALISATION**:
  - `h ≔ ∅`
  - `r ≔ 1`
  - `s ≔ 1`
  - `d :∈ D`
  - `p ≔ 1`
  - `q ≔ 1`
  - `b ≔ FALSE`
  
- **final**:
  - `b ≔ TRUE`
  
- **receive**:
  - `h(r) ≔ d`
  - `r ≔ r + 1`
  - `q ≔ 1 - q`
  
- **send**:
  - `d ≔ f(s)`
  - `s ≔ s + 1`
  - `p ≔ 1 - p`

## Initialisation
- `h` is initialized to an empty collection.
- `r` is initialized to 1.
- `s` is initialized to 1.
- `d` is initialized to an element of set `D`.
- `p` is initialized to 1.
- `q` is initialized to 1.
- `b` is initialized to `FALSE`.

## Invariants
- `p = parity(s)`
- `q = parity(r)`

## Assumptions
- The function `f` is defined and applicable for the variable `s`.
- The set `D` is defined and contains valid elements for `d`.

## Concurrency model
- The system operates with a single process.
- Interaction is through shared state (variables).
- No specific scheduling assumptions are made.

## Other notes
- The model does not utilize bounded queues or arrays beyond the defined variables.
"""

    user2 = brief
    # pat_source = complete_chat(
    #     cfg,
    #     system=stage2_system_message(cfg),
    #     user=user2,
    #     temperature=cfg.temperature_stage2,
    # )
    pat_source = """
#define n 10;

var h = 0;
var r = 1;
var s = 1;
var d = 0;
var p = 1;
var q = 1;
var b = 0;

// Init
Init() = init{
    h = 0;
    r = 1;
    s = 1;
    d = 0;
    p = 1;
    q = 1;
    b = 0;
} -> Skip;

// Final
Final() =
    if (r == n + 1 && b == 0)
    {
        final{ b = 1; } -> Final()
    }
    [] if (!(r == n + 1 && b == 0))
    {
        tau -> Final()
    };

// Receive
Receive() =
    if (p != q)
    {
        receive{ h = d; r = r + 1; q = 1 - q; } -> Receive()
    }
    [] if (!(p != q))
    {
        tau -> Receive()
    };

// Send
Send() =
    if (p == q && s != n + 1 && p == (s % 2) && q == (r % 2))
    {
        send{ d = s; s = s + 1; p = 1 - p; } -> Send()
    }
    [] if (!(p == q && s != n + 1 && p == (s % 2) && q == (r % 2)))
    {
        tau -> Send()
    };

// System
System() = Init(); (Final() ||| Receive() ||| Send());

// Assertions
#define parity_invariant_p (p == (s % 2));
#define parity_invariant_q (q == (r % 2));

#assert System() reaches parity_invariant_p;
#assert System() reaches parity_invariant_q;

#assert System() deadlockfree;
    """

    user3 = pat_source
    final_csp = complete_chat(
        cfg,
        system=stage3_system_message(pat_source, cfg),
        user=user3,
        temperature=cfg.temperature_stage2,
    )

    return RunResult(brief=brief, pat_source=final_csp)
