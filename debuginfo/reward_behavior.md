# Reward behavior overview

This note explains how monster kill rewards for experience and riblets are calculated from the values in `state/monsters/catalog.json`.

## Experience
* `combat_actions._award_player_progress` now grants **exactly** the `exp_bonus` listed for the monster in the catalog, with no additional level-based multiplier.
* The catalog is the source of truth: `_monster_exp_bonus` looks up the monster’s entry in the DB catalog (or the JSON fallback) first and only uses a payload-provided `exp_bonus` when no catalog entry can be found.

## Riblets
* `_award_player_progress` now rolls riblet rewards uniformly between the monster’s `riblets_min` and `riblets_max` values from the catalog, mirroring how ions work.
* The catalog drives the riblet range when possible; payload bounds are only used as a fallback when no catalog entry is available. The range is clamped so the max is at least the min and both are non-negative.
