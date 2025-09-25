# Testing Strategy

Mutants ships a broad pytest suite covering registries, services, commands, and bootstrap
validators. This guide summarises patterns and expectations.

## Test layout

- `tests/test_items_catalog.py` – schema validation and migration warnings.
- `tests/test_items_instances.py` – IID minting, normalisation, and duplicate handling.
- `tests/test_damage_engine.py` and `tests/test_combat_calc.py` – combat math and armour
  calculations.
- `tests/test_commands_*.py` – command orchestration with stub buses.
- `tests/test_bootstrap_validator.py` – ensures environment flags trigger validation.
- `tests/test_fix_iids.py` – verifies the repair tool.

## Running the suite

```bash
pytest
```

Use `pytest -k strike` to focus on a subset. Coverage is reported via `pytest --cov` when
needed.

## Fast feedback loops

- Keep unit tests hermetic by using temporary directories for state root overrides. See
  `tests/test_state_root.py` for patterns using `monkeypatch`.
- Use fixtures to stub feedback buses. Command tests assert on the sequence of emitted
  events.
- When introducing new commands or services, add targeted tests and extend doctest
  examples where appropriate.

## Validator & docs gates

- CI runs `python -m mutants.bootstrap.validate` implicitly via the validator tests and the
  docs workflow.
- Docstring coverage is enforced through `interrogate` (see `make docs-check`). Write
  NumPy-style docstrings with examples so mkdocstrings can render them.

## Performance considerations

- Heavy registry operations should be cached. When adding new APIs consider using the
  `_cache()` pattern in `items_instances` or explicit memoization in services.
- Avoid global state in tests; rely on fixtures to isolate environment variables such as
  `GAME_STATE_ROOT`.

## Related docs

- [Guides → Performance](performance.md)
- [Architecture → Validation](../architecture/validation.md)
- [Contributing](../contributing.md)
