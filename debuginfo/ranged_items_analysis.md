# Ranged item behavior analysis

This note summarizes how ranged items currently work in the codebase and why player-fired bolts do not damage monsters.

## Player `point` command

`point_cmd` checks that the player provided a direction and an item, verifies the item has `charges_max`, and consumes a charge. It then only emits a feedback message.

Key observations:

- The command never resolves a ready target or monster position.
- No combat or damage routines are invoked.
- The only side effect after validation is a `COMBAT/POINT` bus message and decrementing the charge count.

Consequently, firing a ranged item does not produce any attack roll or damage on the intended target.

## Monster ranged attacks

Monster attacks use the combat planner in `monster_actions._apply_player_damage`, which calls `damage_engine.resolve_attack(..., source=plan.source)`. When the selected source is `bolt`, damage is computed and delivered to the player with the proper minimum bolt damage floor.

## Root cause of missing player damage

The player-facing ranged flow stops at the `point` command: there is no logic to perform a `bolt` attack against the readied monster (or any monster along the chosen direction). Since nothing calls the combat/damage engine from the player command, bolts only consume charges and print text without affecting monsters.

A future fix needs to route `point` into the same damage resolution path used for melee strikes (e.g., by invoking a ranged variant of `perform_melee_attack` that sets `source="bolt"` and traces up to four tiles).
