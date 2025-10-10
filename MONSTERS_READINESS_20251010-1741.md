# Monsters Readiness Snapshot — 20251010-1741

## Summary
* SQLite store defines monsters + catalog tables with indexes; schema matches `_COLUMNS`.
* Monsters registry exposes spawn/move/target helpers with no legacy snapshot writers.
* Catalog loads exclusively from SQLite; validation enforces required fields via schema.
* Bootstrap lacks monster spawners; commands limited to inspection/combat workflows.
* No SQLite database present in state directory; runtime counts unavailable.

## SQLite schema status
Source: `src/mutants/registries/sqlite_store.py`

### monsters_instances table
Columns (CREATE TABLE): instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at
Columns (_COLUMNS tuple): instance_id, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at
Indexes: monsters_at_idx(year, x, y, created_at, instance_id)

### monsters_catalog table
Columns: monster_id, data_json
Indexes: (none)

### items_instances table (gear linkage)
Columns (CREATE TABLE): iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at
Columns (_COLUMNS tuple): iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at
Indexes: items_at_idx(year, x, y, created_at, iid), items_owner_idx(owner, created_at, iid), items_origin_idx(origin)

Database check: `mutants.db` not present under state directory; skipped PRAGMA queries.
## Catalog layer
Module: `src/mutants/registries/monsters_catalog.py`

* Loads exclusively from SQLite via `SQLiteConnectionManager`; raises if table empty. Validation uses `_validate_base_monster`.
* Public helpers: functions exp_for, load_monsters_catalog; class methods get, require, list_spawnable
* Schema required fields: monster_id, name, stats, hp_max, armour_class, level, innate_attack, spawn_years, spawnable, taunt; optional properties: exp_bonus, ions_max, ions_min, riblets_max, riblets_min, spells, starter_armour, starter_items; nested required: stats(str, int, wis, dex, con, cha), innate_attack(name, power_base, power_per_level)

## Monsters instances registry
Module: `src/mutants/registries/monsters_instances.py`

* Public API: spawn, move, create_instance, set_target_player, set_ready_target, set_target_monster, save, get, list_all, list_at, update_fields, delete
* Prohibited patterns: none detected (no replace_all/_save/_load/json snapshot writes).
* Catalog base fields referenced when creating instances: monster_id, level, ions_min, ions_max, riblets_min, riblets_max, starter_items, starter_armour, hp_max, armour_class, taunt, innate_attack, spells

## Bootstrap / hooks
Occurrences:
* `src/mutants/bootstrap/lazyinit.py` L137: "target_monster_id": None,
* `src/mutants/bootstrap/runtime.py` L22: MONS_DIR = state_path("monsters")

## Commands coverage
Modules referencing monsters:
* `src/mutants/commands/combat.py`
* `src/mutants/commands/look.py`
* `src/mutants/commands/mon.py`
* `src/mutants/commands/statistics.py`
* `src/mutants/commands/strike.py`
* `src/mutants/commands/wear.py`
* `src/mutants/commands/wield.py`

## Gear linkage model
`items_instances.owner` column exists with index `items_owner_idx`; owner expected to hold monster instance IDs for equipped gear.

## Mismatches & risks
* `sqlite_store.py` monsters replace_all path allows wholesale rewrites when `MUTANTS_ALLOW_REPLACE_ALL` is set.
```
L863:     def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
L864:         if not os.getenv("MUTANTS_ALLOW_REPLACE_ALL"):
L865:             raise RuntimeError(
L866:                 "sqlite_store.replace_all is disabled; use targeted ops or bulk_insert_*"
L867:             )
L868:         payloads = []
```

## Suggested next steps
1. Implement bootstrap hook to seed monsters from catalog on world creation.
2. Wire CLI commands for spawning/killing monsters that call store APIs.
3. Connect gear drops to `items_instances.owner` for monster loot handoff.
4. Add automated sync between combat outcomes and monsters registry updates.
5. Populate SQLite catalog + instances tables via migration or importer script.
