# Validation

!!! abstract "Problem"
    Before runtime we must prove that catalog and instance data satisfy invariants so the
    game does not bootstrap into a corrupted state.

!!! info "Inputs"
    - Catalog loader (`items_catalog.load_catalog`)
    - Instance loader (`items_instances.load_instances`)
    - Environment flags controlling execution

!!! success "Outputs"
    - Summary counts of catalog items and instances
    - Hard failure when invariants break

```mermaid
flowchart TD
  subgraph Environment
    DEV[MUTANTS_DEV]
    CI[CI]
    PYTEST[PYTEST_CURRENT_TEST]
    FORCE[MUTANTS_VALIDATE_CONTENT]
    SKIP[MUTANTS_SKIP_VALIDATOR]
  end
  SKIP -->|true| STOP((skip))
  FORCE -->|true| RUN
  DEV -->|true| RUN
  CI -->|true| RUN
  PYTEST -->|true| RUN
  RUN(run) --> LOAD[load_catalog + load_instances(strict=True)]
  LOAD --> SUMMARY[summary dict]
```

## Execution model

- `mutants.bootstrap.validator.run_on_boot()` runs automatically for CLI entry points that
  import the bootstrap module.
- `should_run()` respects `MUTANTS_SKIP_VALIDATOR` (off switch) and `MUTANTS_VALIDATE_CONTENT`
  (force on). Otherwise, pytest, CI, or `MUTANTS_DEV` enable it by default.
- Validation is strict: catalog errors raise `ValueError`, instance duplicates raise
  `ValueError` when `strict=True`.

## Summary payload

`run(strict=True)` returns:

```python
{
    "items": <count>,
    "instances": <count>,
    "strict": True,
}
```

The values help CI assert the validator touched the expected files. Logging at DEBUG level
includes counts for audit.

## Failure modes

- **Schema errors** – Catalog normalisation logs warnings and raises `ValueError` for hard
  failures. CI surfaces the stack trace.
- **Duplicate IIDs** – Instance loader raises with remediation hint. Run
  `python tools/fix_iids.py` to repair and rerun validation.
- **Skipped validation** – Setting `MUTANTS_SKIP_VALIDATOR=1` locally is acceptable for
  quick iteration but CI resets it. Never commit with validator disabled.

## Related docs

- [Registries](registries.md)
- [Migrations](migrations.md)
- [Guides → Testing](../guides/testing.md)
