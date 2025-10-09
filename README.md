# Mutants 3

[![Docs CI](https://github.com/vindeiatrix/mutants3/actions/workflows/docs.yml/badge.svg)](https://github.com/vindeiatrix/mutants3/actions/workflows/docs.yml)
[![Docstring Coverage](https://img.shields.io/badge/docstring%20coverage-95%25%2B-brightgreen.svg)](docs/changelog.md)

Mutants 3 is a turn-based adventure prototype. This repository houses the combat engine,
item registries, and supporting tooling. The documentation set lives in `docs/` and is
built with MkDocs Material + mkdocstrings.

## Documentation

- [System Map](docs/index.md)
- [Quickstart](docs/quickstart.md)
- [Architecture Overview](docs/architecture/overview.md)
- [API Reference](docs/api/index.md)
- [Contributing Guide](docs/contributing.md)

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
pytest
make docs
```

Mutants 3 uses SQLite as its only state backend. The default state root lives under `state/`,
and the SQLite database is stored at `${GAME_STATE_ROOT}/mutants.db` (or `state/mutants.db` when the
environment variable is not set). JSON storage is no longer supported.

Every new terminal session needs the runtime environment variables before launching the game or
running admin commands. In PowerShell, run:

```powershell
cd C:\mutants3-main
.\.venv\Scripts\Activate.ps1
$env:MUTANTS_STATE_BACKEND = "sqlite"
$env:GAME_STATE_ROOT = "C:\mutants3-main\state"
python -m mutants
```

The `python -m mutants` entry point loads the daily litter items into SQLite, so a fresh clone
will contain items without creating JSON files.

## Admin tooling

The `tools/sqlite_admin.py` helper wraps common maintenance commands for the SQLite database:

```bash
PYTHONPATH=src python tools/sqlite_admin.py catalog-import-items
PYTHONPATH=src python tools/sqlite_admin.py stats
PYTHONPATH=src python tools/sqlite_admin.py vacuum
```

To run SQLite's `PRAGMA optimize` (recommended after heavy catalog churn), execute:

```bash
sqlite3 state/mutants.db "PRAGMA optimize;"
```

## Project layout

```text
src/mutants/      # game logic, registries, services, commands
state/            # default catalog and instance data
tests/            # pytest suites covering registries, combat, and commands
docs/             # MkDocs site (architecture, guides, ADRs)
tools/            # maintenance scripts (fix_iids, migrations)
```

## Support

- File bugs or feature requests via GitHub issues.
- Propose architectural changes through ADRs (see `docs/reference/adr-index.md`).
- Join Docs CI by running `make docs-check` locally before opening a PR.
