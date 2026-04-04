# patgen

**Stages:** (1) Read Event-B text or Rust and produce a natural-language requirements documentation. (2) Turn that documentation into a CSP model.

## Running

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # set OPENAI_API_KEY
```

```bash
python -m patgen path/to/file.txt --dump-brief brief.md
```

Writes PAT source to `path/to/file.csp` by default. Use `-o` / `--output` to pick another path.

Example:

```bash
python -m patgen ./files/4_FILE_1.txt --dump-brief brief.md
```

Optional: `--kind eventb|rust` (default: `.rs` → rust, otherwise eventb), `-o` / `--output`, `--dump-brief`.
