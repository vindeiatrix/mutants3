# CI Checks & Gates — Mutants BBS

## Why these checks exist
Our game is intentionally conservative and deterministic. The UI presents 80-col text; small regressions (like hyphen splitting) break the feel. CI must catch these before merges.

## Checks we run (and why)

### 1) Unit tests (PyTest)
- **Goal:** validate core logic (movement edge composition, item naming, transfers, wrap helpers).
- **Why:** catches logic bugs, ensures invariants (e.g., separators only between blocks).

### 2) Verifier smoke tests (optional in CI; always available locally)
- `logs verify edges` — edge symmetry (cur→dir matches neighbor→opp).
- `logs verify separators` — joins never produce leading/trailing/double `***`.
- `logs verify items` — canonical naming rules (A/An, `_`→`-`, numbering).
- **Why:** easy-to-run E2E-like guards; CI may run a subset due to time.

### 3) UI Wrap Probe + Guard (NEW)
- Non-interactive run that issues:

```
logs trace ui on
logs probe wrap --count 24 --width 80
```

- Produces `UI/PROBE raw=…`, `UI/PROBE wrap … lines=[…]`, and either `UI/WRAP/OK` or `UI/WRAP/BAD_SPLIT`.
- **Guard script** parses `state/logs/game.log` and **fails CI** on any hyphen-break regression.
- **Why:** The hyphen wrap bug is subtle and easy to reintroduce by bypassing final-string hardening; the probe + guard create a robust safety net.

## How to run locally

### With Make

```
make logs-probe
make guard-wrap
```

### Direct

```
python -m mutants <<'EOF'
logs trace ui on
logs probe wrap --count 24 --width 80
logs tail 200
EOF
python scripts/guard_wrap.py
```

## Interpreting failures
- `UI/WRAP/BAD_SPLIT` → a regression in wrapping logic or hardening path.
- Dangling `-"` at a diagnostic line end → a line broke at an ASCII hyphen in diagnostics; fix final-string hardening or wrapper options.
- If your terminal shows breaks but `lines=[…]` is clean → terminal pane narrower than 80 columns; engine is correct.
## Core command-UX checks (NEW)
- A tiny **core** pytest file validates the argument-command runner behavior for `get`/`drop` (empty/invalid/success). It runs with the regular test job; no separate CI step is added.
- Keep these tests minimal and stable (assert the canonical feedback lines only), so new commands don’t break CI. Additional command tests can live outside the core set and be run locally or nightly.

## Router prefix checks (NEW)
- Minimal router tests run in the same pytest job to ensure the ≥3-letter unique-prefix rule and single-letter movement aliases (`n/s/e/w`) remain stable.
