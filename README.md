# Mutants — Project Skeleton (No Game Code)

This repo is a Codespaces-ready Python skeleton for the Mutants project.
It intentionally contains **no game logic**. Start adding code under `src/mutants/`.

## Documentation
- [Architecture overview](docs/architecture_overview.md)
- [Commands](docs/commands.md)
- [Items](docs/items.md)
- [Utilities](docs/utilities.md)
- [State layers](docs/STATE.md)
- [Menus](docs/MENUS.md)
- [Save system](docs/SAVES.md)

## Quick start (Codespaces)
- Open in GitHub Codespaces.
- The container installs the package in editable mode.
- Run: `pip install -e .`
- Run: `python -m mutants`.
- Pick a class on the Class Selection screen (1–5), use `stat` to view player details, and press `x` to return to the menu. `Bury` will arrive in a future update.

## Features
- Class Selection & Statistics foundation
- Room rendering + feedback bus (legacy placeholder)

## Structure
- `src/mutants/io/` — input/parse I/O (empty).
- `src/mutants/handlers/` — command handlers (empty).
- `src/mutants/registries/` — state containers (empty).
- `src/mutants/services/` — background/time-based services (empty).
- `src/mutants/data/` — static data/resources (empty).

## Troubleshooting World Loads

World files are loaded from `state/world/*.json` relative to the **current working directory**.

- `WORLD_DEBUG=1` → enable detailed world-load logs.
- `WORLD_STRICT=1` → fail fast if no worlds are found (instead of creating a minimal world).

Example:

```bash
WORLD_DEBUG=1 python -m mutants
# [world] discover_world_years dir=/…/state/world years=[2000]
# [world] load_year request=2000 path=/…/state/world/2000.json
```

Common pitfall: running from the wrong folder. If the game can't find world JSONs
it will create a minimal world unless `WORLD_STRICT=1` is set.
