# Tests Overview — Mutants BBS

## Principles
- **Determinism:** world gen, movement, and item operations have predictable results.
- **UI invariants:** separators, 80-col wrapping, and naming rules must remain stable.
- **Small, focused cases:** many tiny tests > a few giant ones.

## What we test

### Movement & Edges
- Two-sided edge composition (cur vs neighbor) with conservative defaults.
- `logs verify edges` mirrors this with random sampling to catch asymmetries.

### Items & Naming
- Catalog name rules: Title Case, `_`→`-`, A/An articles, numbering "(1)", "(2)", …
- Ground capacity (≤6) and inventory cap (10) with overflow swap behavior.
- **Wrap-specific:** hyphenated tokens never split at `-`; NBSP after article.

### Inventory & Transfers
- `get`/`drop` prefix targeting, no “(1)/(2)” targeting.
- Overflow swaps: random swap to/from ground per caps.

### UI & Rendering
- Separator placement: only between blocks; never leading/trailing.
- Wrapping to exactly 80 columns; hyphenated tokens and article binding tested.

## Where to add tests
- `tests/` mirrors source domains (e.g., `test_wrap.py`, `test_items.py`, `test_edges.py`).
- Add a regression test per bug class (e.g., hyphen wrap): assert no `-\n` at width=80.

## Running tests

```
pytest -q
```

## CI notes
- Unit tests run by default in CI.
- Wrap probe/guard (see docs/ci_checks.md) complements tests to catch integration-level wrap regressions.
