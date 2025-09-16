# Player State Layers

Mutants now separates player data into three layers so we can evolve the game
without touching the golden templates shipped in the repo.

## 1. Template (read-only)
- Path: `state/playerlivestate.json`
- Loaded at startup and never modified at runtime.
- Provides baseline records for each supported class (`player_thief`,
  `player_priest`, `player_wizard`, `player_warrior`, `player_mage`).

## 2. Save (mutable, persistent)
- Path: `state/savegame.json`
- Schema: `{ "meta": {...}, "players": {<class_id>: {...}}, "active_id": "..." }`
- `meta` currently contains `schema_version` (1), `created_at`, and `updated_at`.
- Written atomically (temp → fsync → rename) whenever the active class changes
  or when the process exits cleanly. Corrupt saves are backed up to
  `savegame.bak.<timestamp>` and rebuilt from the template.

## 3. Live (in-memory)
- The `StateManager` owns `SaveData` (mutable), exposes a compatibility view via
  `state_manager.legacy_state`, and drives autosave logic.
- Screens and commands always read the active player via `state_manager`.
- Commands that mutate player data should call `state_manager.mark_dirty()`;
  autosave can be configured later.

### Player record fields
- `id`: stable identifier, e.g. `player_thief`.
- `name`: player label (defaults to the class name).
- `class`: textual class name ("Thief", "Priest", …).
- `level`: integer ≥ 1.
- `exp_points`: integer ≥ 0.
- `hp`: `{ "current": int, "max": int }` with `0 ≤ current ≤ max`.
- `stats`: `{ "str", "int", "wis", "dex", "con", "cha" }` integers.
- `ions`, `riblets`: non-negative integers.
- `conditions`: `{ "poisoned", "encumbered", "ion_starving" }` booleans.
- `inventory`: list of item instance IDs (may be empty).
- `pos`: `[year, x, y]` integers; year stays in sync with the loaded world.
- Additional keys (notes, exhaustion, armour, etc.) are preserved.

### Example

Template fragment:

```json
{
  "players": [
    {
      "id": "player_thief",
      "name": "Thief",
      "class": "Thief",
      "level": 1,
      "hp": {"current": 18, "max": 18},
      "ions": 30000,
      "riblets": 0,
      "stats": {"str": 15, "dex": 14, "wis": 8, "int": 9, "con": 15, "cha": 16},
      "conditions": {"poisoned": false, "encumbered": false, "ion_starving": false},
      "pos": [2000, 0, 0]
    }
  ],
  "active_id": "player_thief"
}
```

Save fragment:

```json
{
  "meta": {"schema_version": 1, "created_at": "2024-04-18T00:00:00Z", "updated_at": "2024-04-18T00:05:00Z"},
  "players": {
    "player_thief": {
      "id": "player_thief",
      "name": "Thief",
      "class": "Thief",
      "level": 1,
      "hp": {"current": 18, "max": 18},
      "ions": 29500,
      "riblets": 5,
      "stats": {...},
      "conditions": {...},
      "pos": [2000, 1, 0]
    }
  },
  "active_id": "player_thief"
}
```

The save keeps the template structure but holds live values (position, money,
conditions, etc.).
