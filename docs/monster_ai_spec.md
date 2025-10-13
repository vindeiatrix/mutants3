# Monster AI Turn Policy (MajorBBS Style)

## 1. High-Level Summary
Every monster turn executes in the same synchronous room loop that powers player keystrokes. Each tick pulls the monster state, evaluates integer 0–99 rolls, prints templated text, applies the effect, and finishes before the next input is read. There are no background timers or hidden schedulers—the behaviour is entirely deterministic apart from the explicit `rand(0,99)` gates, matching the feel documented in the captured game logs.

## 2. Global Action Cascade (Priority Gates)
Evaluate the following gates, in order, every time a monster shares a room with a player target. Each gate only fires when the monster meets the condition **and** a `rand(0,99)` roll is strictly less than the configured percentage.

| Priority | Gate    | Condition                                                                                     | Default Roll Threshold |
|----------|---------|-----------------------------------------------------------------------------------------------|-------------------------|
| 1        | **FLEE**   | `hp.current / hp.max * 100 < FLEE_HP%`. If true, roll `< FLEE_PCT`.                                | `FLEE_HP% = 25`, `FLEE_PCT = 10` |
| 2        | **HEAL**   | `hp.current / hp.max * 100 < HEAL_AT%` **and** `ions ≥ HEAL_COST`. Roll `< HEAL_PCT`.                | `HEAL_AT% = 80`, `HEAL_PCT = 20` |
| 3        | **CONVERT**| `(ions / ions_max * 100 < LOW_ION%)` **and** `(inventory not empty OR ground items present)`. Roll `< CONVERT_PCT`. | `LOW_ION% = 50`, `CONVERT_PCT = 20` |
| 4        | **CAST**   | `ions ≥ SPELL_COST`. Roll `< CAST_PCT`. Spell resolution makes its own success roll; on failure consume half cost rounded down. | `CAST_PCT = 25` |
| 5        | **ATTACK** | Ready weapon or innate available. Roll `< ATTACK_PCT`.                                             | `ATTACK_PCT = 35` |
| 6        | **PICKUP** | Ground items present. Roll `< PICKUP_PCT`.                                                       | `PICKUP_PCT = 15` |
| 7        | **EMOTE**  | Always available. Roll `< EMOTE_PCT`.                                                             | `EMOTE_PCT = 10` |
| 8        | **IDLE**   | No other gate succeeded.                                                                        | — |

### Wake & Retarget Rolls
When a player issues `LOOK` while a monster is present, immediately roll `rand(0,99) < WAKE_ON_LOOK` to pull the monster into the cascade. When a player enters the room, roll `rand(0,99) < WAKE_ON_ENTRY`. Defaults: `WAKE_ON_LOOK = 15`, `WAKE_ON_ENTRY = 10`. Species may override either within ±10 of the global value.

### Gate Adjustments
* If ions percentage drops below `LOW_ION%`, apply the ion-scarcity adjustments in §4 before the next cascade evaluation.
* When a monster’s equipped breakable weapon becomes cracked, apply the penalties in §3 before re-entering the cascade.

## 3. Attack Type Selection
All monsters have an innate attack profile (`innate_attack.name`, `power_base`, `power_per_level`, and optional `message`). Within the ATTACK gate, apply the following sub-selection:

| Weapon Mix | Base Weights | Notes |
|------------|--------------|-------|
| Melee + ranged item equipped | Melee 70%, Ranged 20%, Innate 10% | Reduce the weight of any weapon flagged as cracked by 50%. Re-normalise remaining weights. |
| Melee only | Melee 95%, Innate 5% | |
| Ranged only | Ranged 90%, Innate 10% | Applies to monsters whose readied item has `ranged: true` and no melee alternative. |
| No item | Innate 100% | The innate template drives the attack text and damage. |

**Innate Bias Modifier:** Monsters that should favour their innate ability adjust the innate weight by +5 to +10 percentage points (`INNATE_WEIGHT_MOD`). Creatures that almost never use the innate attack set it to −5 to −10. Clamp the final innate chance to the range `[0, 95]` before normalising.

**Cracked Weapon Response:** When a weapon cracks (§5), halve its weight, add +10 to `PICKUP_PCT`, and add +5 to `FLEE_PCT` until the monster switches weapons, finds a replacement, or the fight ends.

**Ranged Preference Flag:** Monsters defined with only ranged starters (e.g., Rad Swarm Matron’s `Acid Gland`) inherit the ranged-only table automatically. Future catalog entries that should bias ranged even when melee exists can set a `prefers_ranged` hint (see §12).

## 4. Ion Economy & Spellcasting
* **Conversions:** A successful CONVERT gate consumes either the top inventory item or the richest ground item (highest `ion_value`) and grants ions equal to that item’s `ion_value`. Emit the convert message in §9 and remove the item from the source container.
* **Healing:** HEAL spends `HEAL_COST = 5` ions by default and restores 15% of max HP, capped at missing HP. If the monster lacks sufficient ions, skip the gate.
* **Casting:** CAST deducts the configured spell cost (default `SPELL_COST = 10`). After the gate succeeds, roll spell success (default 75%). On failure, still deduct half cost (rounded down) and print the attempt text only. On success, print both attempt and success messages, apply spell effects, and deduct the full cost.
* **Low Ion Adjustments:** While `(ions / ions_max * 100) < LOW_ION%`, reduce both `CAST_PCT` and `HEAL_PCT` by 40% (multiplicative) and increase `CONVERT_PCT` by +10 absolute points. Remove the modifiers once ions recover above the threshold.

## 5. Weapon Durability & Crack Handling
* Use the item catalog’s `nondegradable` flag to mark unbreakable weapons (`nondegradable: true`). All other weapons may crack.
* On each successful hit with a breakable weapon, roll `rand(0,99) < CRACK_CHANCE`. Default `CRACK_CHANCE = 5`.
* When a crack occurs, set the monster’s weapon state to `cracked`. From that point the weapon’s damage is reduced by 25% and the attack selection penalties in §3 apply.
* Unbreakable weapons never crack. If the monster switches items, clear the `cracked` state for the newly equipped weapon.

Represent the weapon state with the transient fields:
* `weapon_state`: `"intact"`, `"cracked"`, or `"none"`.
* `weapon_unbreakable`: copy of the item’s `nondegradable` boolean for quick checks.

## 6. Fleeing Mindset
A monster enters the flee mindset when:
1. `hp.current / hp.max * 100 < FLEE_HP%`, or
2. Its active weapon is cracked **and** the opposing player’s level exceeds the monster’s `level` by ≥5.

Flee is still probabilistic—the monster can fail the roll and proceed to later gates, matching the behaviour seen when battered creatures keep fighting in the logs. Keep the flee roll first so cracked weapons influence the entire loop.

## 7. Personality Nudges from Existing Data
Apply lightweight adjustments derived from catalog fields. All modifiers stack but clamp results to sensible ranges (e.g., any `*_PCT` stays between 0 and 90).

| Trait Derivation | Effect |
|------------------|--------|
| **Caster-ish:** Monster has at least one entry in `spells`. | `CAST_PCT +10`, `ATTACK_PCT −5`.
| **Brave:** `stats.str` and `stats.con` both ≥ 14. | `FLEE_HP% −5` (min 10).
| **Skittish:** `hp_max ≤ 20` or `stats.con ≤ 8`. | `FLEE_HP% +5` (max 40).
| **Emoter:** `taunt` non-empty **or** `stats.cha ≥ 10`. | `EMOTE_PCT +5`.
| **Converter-inclined:** Inventory includes high-ion items at spawn (`starter_items` containing anything with `ion_value ≥ 1000`). | Set `LOW_ION% = 70`, `CONVERT_PCT +10`.
| **Heavy innate flavour:** `innate_attack.power_base ≥ 12` or innate message customised. | `INNATE_WEIGHT_MOD +5`.
| **Ion poor:** `ions_max ≤ 10`. | `LOW_ION% +10` to encourage earlier conversions.

These rules require no catalog changes and give each monster a distinct tilt.

## 8. Level Influence
Compare monster `level` with the engaged player level.
* If monster is ≥5 levels below the player: `FLEE_PCT +5`, `ATTACK_PCT −5`.
* If monster is ≥5 levels above the player: `ATTACK_PCT +5`.
* Recompute these nudges whenever the target changes.

## 9. Text Output Catalog
Use the following strings with `{monster}` resolved to the monster’s display name (include the serial suffix if present), `{weapon}` to the item name, `{spell}` to the spell title, `{item}` to the item picked or dropped, `{dir}` to the exit direction, and `{target}` when applicable. Stick with the possessive “his” to mirror the original captures.

* **Melee weapon attack:** `{monster} has hit you with his {weapon}!`
* **Ranged attack (projectile):** `{monster} shoots a bolt from his {weapon}!`
* **Ranged attack (other):** `{monster} fires his {weapon} at you!`
* **Innate attacks (rotate or choose per monster via `innate_attack.message`):**
  * `{monster} bites you!`
  * `{monster} smashes a fist into you!`
  * `{monster} touches you!`
  * `{monster} stabs its razor claws at you!`
  * `{monster} lashes his tentacles at you!`
  * `{monster} hurls raw energy at you!`
  * `{monster} scorches you with primal flame!`
* **Cast attempt:** `{monster} waves his arms in the air frantically, and begins to chant!`
* **Cast success:** `The {monster} uses {spell} on you!`
* **Heal:** `{monster}'s body is glowing!`
* **Convert:** `You see a blinding white flash illuminate from {monster}'s body!`
* **Pickup:** `{monster} picked up {item}.`
* **Drop:** `{monster} dropped {item}.`
* **Weapon crack:** `{monster}'s {weapon} cracks!`
* **Arrive:** `{monster} has just arrived from {dir}.`
* **Leave:** `{monster} has just left {dir}.`
* **Wake trigger reminder:** After LOOK or ENTRY wake rolls fire, echo the monster’s standard taunt (already stored in catalog) if successful.

## 10. Emote Library
Keep 90s flavour and use randomly when the EMOTE gate fires.

1. `{monster} is looking awfully sad.`
2. `{monster} is singing a strange song.`
3. `{monster} is making strange noises.`
4. `{monster} looks at you.`
5. `{monster} pleads with you.`
6. `{monster} is trying to make friends with you.`
7. `{monster} is wondering what you're doing.`
8. `{monster} is laughing.`
9. `{monster} is grunting.`
10. `{monster} is sniffing around.`
11. `{monster} is sitting down.`
12. `{monster} is thinking.`
13. `{monster} growls: Meet your doom!`
14. `{monster} hisses ominously.`
15. `{monster} talks: I serve to kill.`
16. `{monster} glares into the distance.`
17. `{monster} mutters about riblets.`
18. `{monster} twitches nervously.`
19. `{monster} flexes menacingly.`
20. `{monster} hums an off-key melody.`

## 11. Species Notes (Current Catalog)
Tailor these adjustments when instantiating each template in `state/monsters/catalog.json`.

| Monster (catalog `monster_id`) | Suggested Tweaks |
|--------------------------------|-------------------|
| `junkyard_scrapper` | Starts with melee only (`Rusty Shiv`). Use melee-only weights. Low HP (`hp_max = 10`) ⇒ apply the Skittish bump (`FLEE_HP% = 30`). Inventory item (`Bolt Pouch`) has modest ions so conversions stay default. |
| `rad_swarm_matron` | Carries `Acid Gland` (treat as ranged) plus innate `Toxic Bite`. Has spell list (`Acid Spit`) ⇒ caster adjustments (`CAST_PCT 35`, `ATTACK_PCT 30`). Constitution 14 ⇒ counts as Brave; set `FLEE_HP% = 20`. Because the gland is ranged-only, use the ranged table and allow `INNATE_WEIGHT_MOD +5` for venom theme. |
| `titan_of_chrome` | Heavy melee (`Hydraulic Fist`) and strong innate. High strength/con (≥14) ⇒ Brave (`FLEE_HP% = 20`). Set `INNATE_WEIGHT_MOD +5` to showcase `Hydraulic Slam`. With two spells, also apply caster tilt but cap `CAST_PCT` at 35. Increase `EMOTE_PCT` to 15 because of high charisma. |

Future catalog additions such as Djinni or Evil Pegasus should mark `prefers_ranged = true` and spawn with `nondegradable: true` ranged gear to inherit the ranged-only weights without extra hooks.

## 12. Minimal Schema Additions
Existing schemas already expose:
* `nondegradable` on items → reuse as `weapon_unbreakable` at runtime.
* `innate_attack.message` optional string → populate for monsters needing bespoke innate text.

Optional runtime hints (no persistence change required) to stash alongside monster instances:
* `prefers_ranged: bool` – derived from spawn data to bias attack sub-selection.
* `weapon_state: Literal["intact","cracked","none"]` – maintained per instance.

If future monsters require persistent overrides for wake rolls, add `wake_on_look` and `wake_on_entry` integers to the monster catalog schema; default to `null` to keep current entries valid.

## 13. Implementation Checklist
- [ ] Implement the cascade order with the integer thresholds listed in §2.
- [ ] Add the ATTACK sub-selection logic and cracked-weapon penalties from §3.
- [ ] Hook the ion economy adjustments, convert resource swap, and low-ion modifiers from §4.
- [ ] Track weapon durability using `nondegradable` and `CRACK_CHANCE = 5` (see §5).
- [ ] Apply flee mindset logic, including cracked-weapon panic, without forcing every turn (see §6).
- [ ] Derive per-monster nudges from existing stats and inventory as outlined in §7.
- [ ] Apply level-based nudges when the target changes (see §8).
- [ ] Emit the text catalog strings and emotes verbatim (see §§9–10).
- [ ] Configure species-specific tweaks for current catalog entries (see §11).
- [ ] Add optional hints/fields only if an equivalent does not already exist (see §12).

