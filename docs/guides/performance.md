# Performance Guide

Combat and loot resolution happen frequently, so we keep the hot paths lean and predictable.

## Hot paths

- **Damage calculation** – `services.damage_engine` is pure and avoids disk I/O by reading
  from registries once per attack. Keep additional lookups memoised in the calling command.
- **Instance registry** – `items_instances._cache()` maintains an in-memory snapshot keyed
  by file mtime. Call `invalidate_cache()` after writing to ensure subsequent reads see the
  latest state.
- **Loot distribution** – `services.combat_loot.drop_monster_loot` iterates over small
  collections. Avoid expensive per-entry operations; precompute catalog lookups when
  possible.

## Profiling tips

- Use `PYTHONPROFILEIMPORTTIME=1` when starting the CLI to measure import overhead.
- Wrap new services with `cProfile` during development to detect regressions.
- Prefer batch reads from registries instead of repeated `load_instances()` calls.

## Avoiding regressions

- Keep registries side-effect free except for explicit write operations. Unexpected
  mutations make caching brittle.
- When adding new fields to instances, update `_normalize_instance` so cached data remains
  consistent.
- Document performance-sensitive choices in ADRs so future contributors understand the
  trade-offs.

## Related docs

- [Architecture → Registries](../architecture/registries.md)
- [Architecture → Damage & Strike](../architecture/damage-and-strike.md)
- [Reference → ADR Index](../reference/adr-index.md)
