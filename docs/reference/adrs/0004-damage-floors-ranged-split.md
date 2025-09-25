# ADR-0004: Damage Floors and Ranged Power Split

- **Status**: Accepted
- **Date**: 2024-05-20
- **Deciders**: @team-mutants
- **Tags**: combat, schema

## Context

Legacy catalog entries stored a single `base_power` value and the combat system assumed
flat minimum damage for bolts and innate attacks. Balancing required separating melee and
bolt values plus enforcing minimum damage floors.

## Decision

- Introduce `base_power_melee` and `base_power_bolt` in the catalog. Ranged items must
  define both. Legacy `base_power` is aliased temporarily with warnings.
- Codify minimum damage floors (`MIN_BOLT_DAMAGE`, `MIN_INNATE_DAMAGE`) in
  `commands.strike`.
- Clamp melee damage on first contact using `_clamp_melee_damage` so maximum HP is not
  exceeded on opening swings.

## Consequences

- Scripts and tooling must set both base power fields for ranged items.
- Migration script `scripts/expand_item_power_fields.py` keeps historical data compatible.
- Combat balance adjustments now tweak separate melee and bolt numbers without side
  effects.
