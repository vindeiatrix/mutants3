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

The default state root lives under `state/`. Override it by setting `GAME_STATE_ROOT` before
running commands.

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
