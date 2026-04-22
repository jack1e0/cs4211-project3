# Automated PAT Generation

### Pipeline Description

**Stage 1:** Input Event-B text or Rust file --> Produce a natural-language requirements documentation
**Stage 2:** Input documentation + manual assertions --> Produce a CSP# file
**Stage 3:** Input CSP# file + more CSP# examples --> Produce a verified final CSP# file

### Local Setup

**Setup environment**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```
Then, set the OpenAI key in `.env`.

**Run pipeline**

```bash
python -m patgen path/to/input_eventb_file.txt --dump-brief path/to/brief.md --assertions path/to/manual_assertions.txt
```

Example:

```bash
python -m patgen files/doors.txt --dump-brief brief.md --assertions files/doors_assertions.txt
```

The final PAT model will be written to the same directory and filename as input file by default (e.g. `./files/doors.csp`). Use `-o` / `--output` to pick another path.
