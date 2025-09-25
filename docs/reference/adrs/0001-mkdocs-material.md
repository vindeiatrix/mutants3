# ADR-0001: MkDocs Material with mkdocstrings

- **Status**: Accepted
- **Date**: 2024-05-20
- **Deciders**: @team-mutants
- **Tags**: docs, tooling

## Context

We needed first-class, linkable documentation that renders docstrings, diagrams, and
architecture guides for humans and AI assistants. Existing Markdown files were ad hoc,
duplicated, and lacked automation.

## Decision

Adopt [MkDocs](https://www.mkdocs.org/) with the Material theme and mkdocstrings plugin.

- Author content in `docs/` following the new information architecture.
- Generate API reference pages directly from Python docstrings.
- Enforce quality gates (vale, markdownlint, codespell, interrogate) via CI and pre-commit.

## Consequences

- Contributors run `make docs` for local previews.
- Docstring quality directly affects docs CI; missing NumPy-style docstrings fail builds.
- GitHub Pages deployment is automated and future changes require updating this ADR.
