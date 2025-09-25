# Contributing

Mutants welcomes contributions that respect the runtime invariants and documentation
standards outlined here.

## Workflow

1. Fork and clone the repository.
2. Create a feature branch (do not commit to `main`).
3. Activate a virtual environment and install dev dependencies: `pip install -e .[dev]`.
4. Run `pytest` and `make docs-check` before pushing.

## Code style

- Python code follows `black`-compatible formatting (PEP 8) and uses type hints.
- Docstrings use the **NumPy** style. Include `Parameters`, `Returns`, `Raises`, and
  `Examples` where helpful. See `mutants.registries.items_instances` for reference.
- Public APIs should be imported in module `__all__` declarations when appropriate.

## Documentation

- Author content under `docs/` in Markdown. Keep sections concise and link across the site.
- Architecture pages must include context boxes and Mermaid diagrams.
- Run `make docs` to ensure `mkdocs build --strict` succeeds. CI enforces zero warnings,
  markdownlint, vale, codespell, interrogate, and link checking.

## Testing

- Add or update pytest coverage for new behaviour.
- Use fixtures to avoid mutating real state. Override `GAME_STATE_ROOT` in tests when
  necessary.
- Ensure docstring examples remain valid by running `pytest --doctest-glob="*.py"` when
  adding doctests.

## Commit messages & PRs

- Write descriptive commit messages. Group doc updates logically.
- Include links to relevant ADRs when altering architecture decisions.
- Pull requests must pass Docs CI before review. Add screenshots only when modifying UI.

## Community guidelines

- Prefer discussions in GitHub issues.
- Respect ADR decisions; propose updates by submitting a new ADR.
- Keep secrets out of the repository. Use environment variables for configuration.
