# Quickstart

This guide gets you ready to explore the code, run the validator, and iterate on
documentation.

!!! abstract "Problem"
    New contributors need a reproducible workflow for exploring the unified state root,
    running the bootstrap validator, and previewing the docs.

!!! info "Inputs"
    - Python 3.11+
    - `pipx` or `pip`
    - Optional: `node` for Markdown linting via `npx`

!!! success "Outputs"
    - Editable virtual environment with Mutants 3 installed
    - Locally rendered docs via `make docs`
    - Validator output proving the state root is coherent

## 1. Clone and install

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

## 2. Inspect the project layout

```text
src/mutants/           # gameplay code
state/                 # default unified state root (items, monsters, config)
docs/                  # MkDocs documentation set (this site)
tools/                 # maintenance scripts, e.g. fix_iids.py
.github/workflows/     # CI checks including docs gate
```

## 3. Run the bootstrap validator

The validator ensures catalog and instance registries satisfy invariants before the game
starts.

```bash
python -m mutants.bootstrap.validate
```

On success the command exits silently. Validation errors enumerate which invariants
failed and reference repair scripts such as `tools/fix_iids.py`.

## 4. Build the docs

```bash
make docs
```

The `make docs` target installs the MkDocs toolchain if necessary and builds the site
with `--strict` to guarantee zero warnings. Use `make docs-serve` to preview the site
locally on <http://localhost:8000>.

## Next steps

- Follow the [Architecture Overview](architecture/overview.md) to understand how layers
  compose runtime behaviour.
- Read [Guides → Extending Items](guides/extending-items.md) before editing catalog data
  or loot tables.
- Keep the [Glossary](reference/glossary.md) handy to translate in-game terminology into
  code concepts.
