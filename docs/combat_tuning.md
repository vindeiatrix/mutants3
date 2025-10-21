# Combat Tuning Reference

This guide documents every field in the combat configuration, how it maps to the
runtime gates, and how to tune healing economics without breaking archival
requirements. Designers can override the defaults by writing
`state/config/combat.json`; the runtime merges any supplied values onto the
frozen dataclass returned by `mutants.services.combat_config.load_combat_config`.
Each entry below lists the default pulled from the baseline configuration, plus
the requirement identifier that demands the behaviour.

## Configuration overview

| Field | Default | Requirement ID(s) | Description |
|-------|---------|-------------------|-------------|
| `wake_on_look` | 15 | AI-SPEC-2 | Wake chance when a player issues `LOOK` into the monster room. |
| `wake_on_entry` | 10 | AI-SPEC-2 | Wake chance when a player enters the room. |
| `flee_hp_pct` | 25 | AI-SPEC-3.1 | HP% threshold that unlocks the flee gate. |
| `flee_pct` | 10 | AI-SPEC-3.1 | Gate roll chance once flee is eligible. |
| `heal_at_pct` | 80 | AI-SPEC-3.2 | HP% threshold that makes healing available. |
| `heal_pct` | 20 | AI-SPEC-3.2 | Gate roll chance once healing is eligible. |
| `heal_cost` | 200 | C4, A4 | Ion cost deducted per heal action. |
| `convert_pct` | 20 | AI-SPEC-3.3 | Gate roll chance for converting loot into ions. |
| `low_ion_pct` | 50 | AI-SPEC-3.3 / A4 | Ion percentage that enables low-ion behaviour. |
| `cast_pct` | 25 | AI-SPEC-3.4 | Gate roll chance for spellcasting. |
| `attack_pct` | 35 | AI-SPEC-3.5 | Gate roll chance for standard attacks. |
| `pickup_pct` | 15 | AI-SPEC-3.6 | Gate roll chance for grabbing ground loot. |
| `emote_pct` | 10 | AI-SPEC-3.7 | Gate roll chance for idle emotes. |
| `spell_cost` | 10 | A4 | Base ion cost for successful spellcasts. |
| `spell_success_pct` | 75 | AI-SPEC-5 | Chance for spells to succeed after the cast gate hits. |
| `cracked_pickup_bonus` | 10 | AI-SPEC-3 bias | Bonus pickup chance while wielding cracked gear. |
| `cracked_flee_bonus` | 5 | AI-SPEC-3 bias | Bonus flee chance while wielding cracked gear. |
| `rng_seeds.wake` | `null` | QA-RNG | Optional deterministic seed for wake rolls. |
| `rng_seeds.gates` | `null` | QA-RNG | Optional deterministic seed for gate order rolls. |
| `rng_seeds.loot` | `null` | QA-RNG | Optional deterministic seed for loot rolls. |

*Requirement IDs* refer to the numbered sections in
[`docs/monster_ai_spec.md`](monster_ai_spec.md) or to cross-referenced combat
notes (e.g. C4/A4 for healing economics). QA-RNG refers to internal testing
requirements for deterministic simulations.

## Editing the combat configuration

1. Copy `src/mutants/services/combat_config.py`'s defaults into
   `state/config/combat.json`, and edit only the fields you need.
2. Use integers for all knobs; non-integer overrides are ignored at load time.
3. Restart the runtime or reload the combat config to pick up changes. The
   resolved path is written to `CombatConfig.override_path` for observability.

## Tuning wake and flee behaviour

* **Wake gates (`wake_on_look`, `wake_on_entry`) – AI-SPEC-2:** Higher values
  make monsters more responsive whenever the player looks into or enters their
  room, matching the wake flow outlined in §2 of the AI spec.
* **Flee gate (`flee_hp_pct`, `flee_pct`, `cracked_flee_bonus`) – AI-SPEC-3.1:**
  Lowering `flee_hp_pct` delays when low-health monsters attempt to flee,
  whereas increasing `flee_pct` or the cracked bonus raises the probability once
  the gate is eligible. Keep both aligned so aggressive species still respect
  requirement C13 on persistent targeting while honouring the flee rules.

## Healing gates and cost economics

Healing requires three simultaneous conditions: HP below `heal_at_pct`, ions at
least equal to `heal_cost`, and a gate roll under `heal_pct`.

* **Threshold and probability – AI-SPEC-3.2:** Raising `heal_at_pct` or
  `heal_pct` makes monsters more likely to attempt heals at higher health. Lower
  values confine heals to emergencies.
* **Ion cost – C4 / A4:** `heal_cost` enforces the Thief-style pricing demanded
  by combat note C4 and reconciles the ion economy conflict in architecture
  requirement A4. Increase the cost to make heals rarer due to ion scarcity; cut
  the cost when testing more frequent heals. Keep this knob in sync with player
  heal economics so ledger logging stays balanced.
* **Low-ion behaviour – AI-SPEC-3.3 / A4:** When `ions / ions_max * 100` falls
  below `low_ion_pct`, the cascade reduces heal chances (see §5). Lowering the
  percentage helps low-level monsters conserve ions for emergencies; raising it
  encourages aggressive spending.

## Conversion, casting, and attack knobs

* **Convert gate (`convert_pct`) – AI-SPEC-3.3:** Controls how often monsters
  burn ground loot into ions when eligible. Combine with `low_ion_pct` to dial
  in scarcity pressure.
* **Casting (`cast_pct`, `spell_cost`, `spell_success_pct`) – AI-SPEC-3.4 / A4 / 5:**
  Raising `cast_pct` increases attempts; `spell_cost` adjusts ion drain per
  successful cast, while `spell_success_pct` tunes the follow-up success roll.
* **Baseline aggression (`attack_pct`) – AI-SPEC-3.5:** Higher values favour
  direct attacks after higher priority gates fail. Coordinate with flee and heal
  settings to hit the intended threat curve.
* **Looting and flavour (`pickup_pct`, `emote_pct`, `cracked_pickup_bonus`) –
  AI-SPEC-3.6 / 3.7 / bias:** `pickup_pct` and `emote_pct` manage the tail end of
  the cascade. The cracked pickup bonus ensures broken weapons push monsters
  toward replacements, aligning with the cracked-gear bias in §3.

## Deterministic testing knobs

Use `rng_seeds.wake`, `rng_seeds.gates`, and `rng_seeds.loot` to seed the wake
checks, priority gate rolls, and loot tables respectively. Setting these to
explicit integers produces repeatable combat logs, satisfying QA-RNG goals for
regression tests.
