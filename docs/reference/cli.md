# CLI & Tools

Mutants ships maintenance scripts under `tools/`. They share the unified state root
(`mutants.state.STATE_ROOT`) so overrides apply uniformly.

## `tools/fix_iids.py`

- **Purpose** – detect and repair duplicate item instance IDs.
- **How it works** – scans `items/instances.json`, remints collisions deterministically,
  and rewrites references using `IIDAssigner`.
- **Usage** – `python tools/fix_iids.py [--instances path] [--state-root path]`
- **When to run** – whenever validation fails with duplicate IID errors or after manually
  editing instances outside the registry.

## `tools/migrate_catalog_charges.py`

- **Purpose** – codemod `charges_start` → `charges_max` and clean up `uses_charges` flags.
- **Usage** – `python tools/migrate_catalog_charges.py state/items/catalog.json`
- **Notes** – preserves pretty-printed JSON and enforces ranged items to be non-spawnable
  when they consume charges.

## Validator entry point

- `python -m mutants.bootstrap.validator` runs the same logic as on boot and prints a JSON
  summary when executed directly.
- Use `MUTANTS_VALIDATE_CONTENT=1` to force validation even outside CI.

## Reference

- [Architecture → Registries](../architecture/registries.md)
- [Architecture → Validation](../architecture/validation.md)
