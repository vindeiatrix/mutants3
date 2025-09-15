# Save System

## Paths
- Template: `state/playerlivestate.json` (read-only, shipped with the repo)
- Save file: `state/savegame.json`
- Backups: `state/savegame.bak.<timestamp>` (created when a save is unreadable)

## Atomic writes
- Saves are written through a temp file in the same directory, flushed via
  `fsync`, then renamed into place.
- This keeps the save durable even if the process exits mid-write or the system
  crashes.

## Schema
- `schema_version`: starts at `1`. Future migrations will branch on this value.
- `meta.created_at`: ISO-8601 UTC timestamp for the initial save creation.
- `meta.updated_at`: refreshed on every successful `persist()`.
- `players`: map keyed by class id (`player_thief`, `player_priest`, etc.).
- `active_id`: the class currently in control.

## Autosave & triggers
- Every class switch persists immediately.
- `StateManager.save_on_exit()` flushes pending changes on clean exit.
- Autosave by command-count is wired up but defaults to disabled (`0`).
  Configure `autosave_interval` via runtime config in a later update.
