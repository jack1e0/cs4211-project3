"""Thin OpenAI chat wrapper."""

from __future__ import annotations

from openai import OpenAI

from patgen.config import Config

STAGE1_SYSTEM_DEFAULT = """You are a formal methods assistant. Your job is to read a source \
file (Event-B style text or Rust) and produce a faithful natural-language requirements documentation for another \
model that will encode the system in PAT/CSP-style notation.

Rules:
- Extract only what is stated or clearly implied; do not invent behaviors.
- Use these section headings as a guide to structure the documentation:
  ## System description
  ## Requirements
  ## Constants
  ## Variables
  ## States
  ## Guards
  ## Actions
  ## Initialisation
  ## Invariants
  ## Assumptions
  ## Other notes
- Write clear prose and bullet lists inside sections when helpful."""


STAGE2_SYSTEM_BASE = """You are a formal methods expert. Given a natural-language requirements documentation of a \
system, output a single event-based CSP style (channel CSP) model as plain source text.

Output rules:
- Emit only model source that could be saved to a file and checked by PAT (process definitions, \
#system, #alphabet, #endalphabet, etc. as appropriate for the documentation). No markdown fences, no explanation.

Refer to this sample CSP code of Alternating Bit Protocol as an example:

//=======================Model Details===========================
#define CHANNELSIZE 1;

channel c CHANNELSIZE; //unreliable channel.
channel d CHANNELSIZE; //perfect channel.
channel tmr 0; //a synchronous channel between sender and timer, which is used to implement premature timeout.

Sender(alterbit) = (c!alterbit -> Skip [] lost -> Skip);
                                  tmr!1 -> Wait4Response(alterbit);

Wait4Response(alterbit) = (d?x -> ifa (x==alterbit) {
                                      tmr!0 -> Sender(1-alterbit)
                                  } else {
                                      Wait4Response(alterbit)
                                  })
                          [] tmr?2 -> Sender(alterbit);

Receiver(alterbit) = c?x -> ifa (x==alterbit) {
                                 d!alterbit -> Receiver(1-alterbit)
                            } else {
                                 Receiver(alterbit)
                            };

Timer = tmr?1 -> (tmr?0 -> Timer [] tmr!2 -> Timer);

ABP = Sender(0) ||| Receiver(0) ||| Timer;

#assert ABP deadlockfree;
#assert ABP |= []<> lost;


"""


def stage1_system_message(input_kind: str) -> str:
    return f"{STAGE1_SYSTEM_DEFAULT}\n\nThe input is labeled as: {input_kind}."


def stage2_system_message(config: Config) -> str:
    parts = [STAGE2_SYSTEM_BASE]
    if config.few_shot_system_addon:
        parts.append("\n--- Reference patterns (follow style/conventions, adapt to this brief):\n")
        parts.append(config.few_shot_system_addon)
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
