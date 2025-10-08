.PHONY: docs docs-serve docs-check run-once logs-probe guard-wrap ci-wrap-check \
	sqlite-init sqlite-stats sqlite-vacuum sqlite-purge

DOCS_DEPS = mkdocs-material mkdocstrings[python] mkdocs-mermaid2-plugin

_docs-install:
	python -m pip install --quiet --upgrade pip
	python -m pip install --quiet $(DOCS_DEPS)
	python -m pip install --quiet codespell vale interrogate

# Build the MkDocs site with strict mode.
docs: _docs-install
	PYTHONPATH=src mkdocs build --strict

# Serve the docs locally.
docs-serve: _docs-install
	PYTHONPATH=src mkdocs serve -a 0.0.0.0:8000

# Run the documentation lint suite.
docs-check: _docs-install
	npx markdownlint-cli '**/*.md' --ignore node_modules --ignore CHANGELOG.md --ignore state/world/readme.md
	vale .
	codespell -L "crate,crate's,padd,stati,nd" --skip=site
	interrogate -v -i src --fail-under 95

# Existing gameplay helpers -------------------------------------------------

# Boot the game once and run a UI probe in non-interactive mode
run-once:
	printf 'logs trace ui on\nlogs probe wrap --count 24 --width 80\nlogs tail 1\n' | PYTHONPATH=src python -m mutants

# Just the probe (assumes the game is already warmed)
logs-probe:
	printf 'logs trace ui on\nlogs probe wrap --count 24 --width 80\nlogs tail 1\n' | PYTHONPATH=src python -m mutants

# Local guard (read log file and fail on regression)
guard-wrap:
	./scripts/guard_wrap.py

# CI convenience: run probe then guard
ci-wrap-check: logs-probe guard-wrap

# SQLite administration helpers --------------------------------------------

sqlite-init:
	PYTHONPATH=src python tools/sqlite_admin.py init

sqlite-stats:
	PYTHONPATH=src python tools/sqlite_admin.py stats

sqlite-vacuum:
	PYTHONPATH=src python tools/sqlite_admin.py vacuum

sqlite-purge:
	PYTHONPATH=src python tools/sqlite_admin.py purge
