# ADR-0005: Deterministic Drops Partial Order

- **Status**: Accepted
- **Date**: 2024-05-20
- **Deciders**: @team-mutants
- **Tags**: loot, combat

## Context

Loot drops historically depended on the order of Python dictionary iteration, leading to
non-deterministic results between runs and making tests flaky.

## Decision

- Encode a fixed iteration order in `services.combat_loot.drop_monster_loot`:
  bag entries → skull → armour.
- Annotate each minted or vaporised entry with `drop_source` for audit.
- Log vaporisation events and emit turn log entries so tooling can replay outcomes.

## Consequences

- Tests assert deterministic orderings regardless of Python version.
- Designers can reason about loot tables knowing skulls always spawn if there is space.
- Debug logs clearly show when ground capacity caused vaporisation, aiding tuning.
