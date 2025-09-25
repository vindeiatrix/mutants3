# ADR-0003: Unified State Root

- **Status**: Accepted
- **Date**: 2024-05-20
- **Deciders**: @team-mutants
- **Tags**: state

## Context

Different tools previously resolved state paths relative to their working directory,
leading to mismatched catalog data between CLI utilities and the game runtime.

## Decision

- Centralise state resolution in `mutants.state.STATE_ROOT`.
- Support overrides via `GAME_STATE_ROOT` with path expansion and relative resolution.
- Require all registries and tools to call `state_path(*parts)`.

## Consequences

- Tests can isolate fixtures by setting `GAME_STATE_ROOT`.
- Docs and CLI instructions reference a single mechanism, reducing onboarding friction.
- Any tool bypassing `state_path` is considered a bug and must be fixed.
