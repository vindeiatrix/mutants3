# Mutants — Project Skeleton (No Game Code)

This repo is a Codespaces-ready Python skeleton for the Mutants project.
It intentionally contains **no game logic**. Start adding code under `src/mutants/`.

## Quick start (Codespaces)
- Open in GitHub Codespaces.
- The container installs the package in editable mode.
- Run: `pip install -e .`
- Run: `python -m mutants` (placeholder CLI).

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

