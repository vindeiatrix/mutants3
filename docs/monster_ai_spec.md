# Monster AI Turn Policy (MajorBBS Style)

## 1. High-Level Summary
Monster turns run inside the same synchronous loop that dispatches player commands. The
engine (`mutants.services.monster_actions.execute_random_action`) pulls the monster
payload, rolls explicit integer gates, applies the effect, emits log lines, and yields the
room back to the player prompt. There are no background schedulers: every behaviour comes
from the wake roll (§2) followed by the seven-gate cascade (§3) and the deterministic
helpers in `mutants.services`.

## 2. Wake Triggers & Turn Start
1. **Wake on LOOK:** When a player issues `LOOK` into the monster's room, roll
   `rand(0,99) < WAKE_ON_LOOK` before doing anything else. Default `WAKE_ON_LOOK = 15`.
2. **Wake on ENTRY:** When a player (or ready target) enters, roll `rand(0,99) <
   WAKE_ON_ENTRY`. Default `WAKE_ON_ENTRY = 10`.
3. **No wake ⇒ no action:** If both rolls fail during a tick the monster does nothing that
   turn: no pursuit, no item handling, no emote. Only after a wake success does the
   instance evaluate the priority cascade.
4. **Per-monster tuning:** Use optional monster overrides (see §16) to shift either wake
   threshold within ±10 when catalogue lore demands it.

## 3. Global Action Cascade (Priority Gates)
Once awake and sharing a room with a player target, evaluate the gates below in order.
Each gate fires when its condition is met **and** a `rand(0,99)` roll is strictly less
than the configured percentage. Stop on the first gate that succeeds; otherwise fall
through to IDLE.

| Priority | Gate        | Condition                                                                                           | Default Threshold |
|----------|-------------|------------------------------------------------------------------------------------------------------|-------------------|
| 1        | **FLEE**    | `hp.current / hp.max * 100 < FLEE_HP%`. Then roll `< FLEE_PCT`.                                      | `FLEE_HP% = 25`, `FLEE_PCT = 10` |
| 2        | **HEAL**    | `hp.current / hp.max * 100 < HEAL_AT%` **and** `ions ≥ HEAL_COST`. Roll `< HEAL_PCT`.                | `HEAL_AT% = 80`, `HEAL_PCT = 20` |
| 3        | **CONVERT** | `ions / ions_max * 100 < LOW_ION%` **and** bag or ground has qualifying loot. Roll `< CONVERT_PCT`. | `LOW_ION% = 50`, `CONVERT_PCT = 20` |
| 4        | **CAST**    | `ions ≥ SPELL_COST`. Roll `< CAST_PCT`.                                                              | `CAST_PCT = 25` |
| 5        | **ATTACK**  | Readied weapon or innate available. Roll `< ATTACK_PCT`.                                             | `ATTACK_PCT = 35` |
| 6        | **PICKUP**  | Ground has qualifying items (see §8). Roll `< PICKUP_PCT`.                                           | `PICKUP_PCT = 15` |
| 7        | **EMOTE**   | Always available. Roll `< EMOTE_PCT`.                                                                | `EMOTE_PCT = 10` |
| 8        | **IDLE**    | No other gate succeeded.                                                                             | — |

**Cracked weapon bias:** When the wielded weapon is cracked (see §6) and not enchanted,
halve that weapon's attack sub-weight (§4), add +10 to `PICKUP_PCT`, and +5 to `FLEE_PCT`
until the weapon is replaced or the encounter ends.

## 4. Attack Type Selection
`damage_engine.resolve_attack` already understands the monster payload: melee weapons use
`bag[].derived.base_damage + stats.str // 10`, ranged weapons honour the catalog `ranged`
flag, and innate attacks are described under `innate_attack`. Inside the ATTACK gate pick
an attack source using integer weights.

| Weapon Mix                         | Base Weights                        | Notes |
|-----------------------------------|--------------------------------------|-------|
| Melee + ranged equipped           | Melee 70%, Ranged 20%, Innate 10%    | If the monster carries both, bias melee unless `prefers_ranged` is true (runtime hint).
| Melee only                        | Melee 95%, Innate 5%                 | |
| Ranged only                       | Ranged 90%, Innate 10%               | Applies when the ready item has `catalog[ranged] = true` and no melee alternative is
                                                                              available. |
| No item                           | Innate 100%                          | Uses the per-monster message from `innate_attack.message`. |

* `prefers_ranged` nudges ranged weight to 70% (melee+ranged) or 95% (ranged-only). Set it
  for catalog entries like Djinni or Evil Pegasus when their ranged starter is the marquee
  attack.
* `INNATE_WEIGHT_MOD` remains available for flavour: clamp final innate weight between 0
  and 95 before normalising.
* When the weapon cracks (non-enchanted) halve its sub-weight, apply the cracked bias above
  §3, and trigger the drop logic in §7.

## 5. Ion Economy & Spellcasting
* **Conversions:** A successful CONVERT gate consumes the best qualifying item and grants
  ions via `convert_cmd._convert_value` (catalog `convert_ions`/`ion_value` plus
  `10100 * enchant_level`). Emit the convert text (§13) and remove the item from inventory.
* **Bold rule – no native conversions:** **Only items marked as picked up from the ground
  may be converted.** The AI keeps an `_ai_state["picked_up"]` list populated by the
  pickup routine; anything originating from starter gear (`origin: "native"`) or existing
  equipment is off-limits.
* **Healing:** Spend `HEAL_COST = 5` ions to restore 15% of max HP (capped at missing HP).
  Skip if ions are insufficient.
* **Casting:** Deduct `SPELL_COST = 10` by default. After the gate succeeds roll spell
  success (default 75%). On failure consume half cost (rounded down); on success consume
  the full cost and apply the effect.
* **Low Ion Adjustments:** While `ions / ions_max * 100 < LOW_ION%`, reduce
  `CAST_PCT`/`HEAL_PCT` by 40% (multiplicative) and add +10 absolute to `CONVERT_PCT`.

## 6. Weapon & Armour Durability (Deterministic)
Breakage is deterministic and driven by the wear helpers in
`mutants.services.items_wear` and `mutants.registries.items_instances`.

* Only degradable, non-enchanted items crack. Runtime flag:
  `bag[i].derived.can_degrade = enchant_level == 0 and not catalog[nondegradable]`.
* On each damaging event, compute `wear_amount = items_wear.wear_from_event({...})`.
  Present default: every qualifying hit feeds `{ "kind": ..., "damage": N }` and returns 5.
* Pull the current condition (`items_instances.get_condition`), then compute
  `next_condition = max(0, current_condition - wear_amount)`.
* If `next_condition > 0`, persist it via `items_instances.set_condition`.
* If `next_condition <= 0`, call `items_instances.crack_instance(iid)` which swaps the item
  id to `itemsreg.BROKEN_WEAPON_ID` or `itemsreg.BROKEN_ARMOUR_ID` and clears condition.
* Weapon cracks announce through the combat bus; armour cracks also emit the victim callout
  in `commands.strike`.

Because wear amounts are fixed, every degradable item with starting condition 100 will
crack on the 20th successful damaging hit unless maintenance intervenes. Enchanted or
`nondegradable` catalog entries never crack.

## 7. Broken Equipment Response
Combat logs show the ground littered with shards because monsters actively remove broken
gear.

* **Armour:** When `armour_slot.item_id == itemsreg.BROKEN_ARMOUR_ID`, enqueue
  `monster_actions._remove_broken_armour` as the next high-priority action. The monster
  removes and drops the broken shell immediately after the crack event (before resolving
  lower-priority gates).
* **Weapons:** When a wielded weapon cracks and remains non-enchanted:
  * If the monster already has a replacement equipped (e.g., switched during the same
    gate) or just picked one up, drop the broken weapon immediately.
  * Otherwise schedule a drop within the next one or two cascades: roll `rand(0,99) < 80`
    each turn and, on success, drop the broken weapon before evaluating later gates.
  * While wielding a cracked weapon, apply the cracked bias from §3 and, after the drop,
    fall back to innate or freshly equipped weapons.
* Dropped broken gear stays on the ground to match the archival logs; do not auto-convert
  or auto-destroy it.

## 8. Ground & Inventory Handling
### Pickup Gate
* Ground scan uses `itemsreg.list_instances_at(year, x, y)` and scores each item via
  `_score_pickup_candidate`, which favours high `derived.base_damage` and `ion_value`.
* **Hard filter:** Skip any instance whose `item_id` resolves to
  `itemsreg.BROKEN_WEAPON_ID` or `itemsreg.BROKEN_ARMOUR_ID`; monsters never pick up broken
  placeholders.
* On pickup set the instance `origin` to `"world"`, append a normalised bag entry via
  `_build_bag_entry`, and stash the iid in `_ai_state["picked_up"]` for conversion
  tracking.

### Infinite Carry
`monsters_state._normalize_item` records `derived.effective_weight`, but no encumbrance
check runs for monsters. Treat monster bags as weightless so AI decisions never gate on
load. (Players still obey encumbrance rules.)

### On-the-fly Upgrades
* **Weapons:** Whenever the monster acquires or observes an item whose computed damage
  (`bag[i].derived.base_damage + stats.str // 10`) beats the currently wielded weapon,
  immediately swap: set `monster["wielded"]` to the best iid, move the displaced weapon to
  the bag, and refresh derived stats via `monsters_state._refresh_monster_derived`.
  * Melee preference: if both melee and ranged are present, pick the best melee unless
    `prefers_ranged` is true.
  * Ranged-only monsters (Djinni, Evil Pegasus) set `prefers_ranged = true` so the ranged
    winner is respected.
* **Armour:** Compare `bag[i].derived.armour_class` (or catalog `armour_class` +
  enchantment) against the equipped payload. If the new armour is strictly higher or the
  monster is currently unarmoured, equip it immediately. Move the displaced piece into the
  bag unless it is already broken, in which case drop it per §7.
* **Innate vs Item:** If no item beats innate damage, leave the monster innate-only and
  rely on the attack weights in §4.

## 9. Fleeing Mindset & Personality Nudges
* Core flee trigger: `hp.current / hp.max * 100 < FLEE_HP%` (default 25). Crack-induced
  panic still applies: when the wielded weapon is cracked add an extra flee check if the
  opposing player is ≥5 levels higher.
* Level-relative courage:
  * If the monster is ≥5 levels **below** the player: `FLEE_PCT +5`, `ATTACK_PCT −5`.
  * If the monster is ≥5 levels **above** the player: `ATTACK_PCT +5`.
* Species hints can layer small nudges (±5) based on catalog lore—e.g., swarm creatures
  might add to `PICKUP_PCT` for brood tags, while undead reduce `FLEE_PCT`. Avoid broad
  stat-based rules; rely on current HP, ion state, equipment condition, and explicit
  species tags.

## 10. Pursuit & Movement
When a player leaves the room and the monster is not actively fleeing, attempt pursuit on
its very next turn.

* Base chase chance: roll `rand(0,99) < 70`. On success, follow the last known exit. If the
  exit is blocked, fall back to the pathing helpers in `world.years` (same logic players
  use when travelling between tiles).
* Distraction modifiers applied before rolling:
  * −20 when the ground list contains a non-broken item that would pass the pickup gate.
  * −15 when ions are below `LOW_ION%` (the monster wants to convert).
  * −20 when HP is below 40% (the monster prioritises heal/flee).
  * −25 after a crack event until a replacement is found.
* If the monster fails pursuit (either by roll or because distractions pre-empted pursuit)
  resolve the cascade normally; pickup/convert/heal actions may occur before movement on
  that turn, matching the captured logs where monsters loot before chasing.

## 11. Post-Kill Bonus Action
When a monster kills a player or another monster (`_handle_player_death` or future PvE
hooks), immediately grant one extra cascade evaluation before returning to the global
loop.

* Run a single gate pass using the same priorities. Skip the wake check—the monster is
  already active.
* Default: 25% of these bonus actions force the PICKUP gate (if drops are present).
  Otherwise evaluate the cascade normally; heal and convert remain valid.
* After the bonus action, resume the standard turn order.

## 12. Text Output Catalog
Use the strings below with `{monster}` resolved to the display name, `{weapon}` to the
item label, `{spell}` to the spell title, `{item}` to ground loot, `{dir}` to exits, and
`{target}` when applicable. Keep the possessive "his" to match the original dumps.

* **Melee attack:** `{monster} has hit you with his {weapon}!`
* **Ranged projectile:** `{monster} shoots a bolt from his {weapon}!`
* **Ranged other:** `{monster} fires his {weapon} at you!`
* **Innate attack:** Pull per-monster text from `innate_attack.message` in the monster
  catalog. Every species should define its own line (no shared pool).
* **Cast attempt:** `{monster} waves his arms in the air frantically, and begins to chant!`
* **Cast success:** `The {monster} uses {spell} on you!`
* **Heal:** `{monster}'s body is glowing!`
* **Convert:** `You see a blinding white flash illuminate from {monster}'s body!`
* **Pickup:** `{monster} picked up {item}.`
* **Drop:** `{monster} dropped {item}.`
* **Weapon crack:** `{monster}'s {weapon} cracks!`
* **Arrive:** `{monster} has just arrived from {dir}.`
* **Leave:** `{monster} has just left {dir}.`
* **Wake success:** After a LOOK/ENTRY wake roll succeeds, print the catalog taunt.

## 13. Emote Library
Keep the 90s flavour emotes when the EMOTE gate fires.

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

## 14. Species Notes (Current Catalog)
Use these nudges when instantiating the templates in `state/monsters/catalog.json`.

| Monster (`monster_id`)   | Notes |
|--------------------------|-------|
| `junkyard_scrapper`      | Starts melee-only (`Rusty Shiv`). Keep melee-only weights. Low HP and level vs most players mean frequent flee rolls; apply the −5 ATTACK / +5 FLEE level differential when outmatched. Drop cracked shiv fragments promptly to match debris-heavy zones. |
| `rad_swarm_matron`       | Carries `Acid Gland` (ranged) and `Toxic Bite`. Set `prefers_ranged = true` so bolts fire first, but leave a 10% innate chance for venom flavour. Armour upgrades favour `Chitin Plating`; if a better shell drops, swap immediately to maintain brood matron toughness. |
| `titan_of_chrome`        | Heavy melee + strong innate. Leave `prefers_ranged = false`. Armour rarely cracks (`nondegradable` fists), so focus on ATTACK and CONVERT gates. When a replacement gauntlet appears, treat it as a melee upgrade even if ranged gear is present. |
| Future `djinni`, `evil_pegasus` | Flag as `prefers_ranged = true`, supply nondegradable ranged starters, and define bespoke innate lines in the catalog so their spell-flavoured attacks stay unique. |

## 15. Minimal Schema Additions
Existing state already tracks everything required:

* `bag[].origin` distinguishes native vs world loot.
* `_ai_state.picked_up` exists for pickup tracking.
* `innate_attack.message` is per-monster.

Optional runtime hints (no persistence changes) may live on the monster instance:

* `prefers_ranged: bool`
* `wake_on_look` / `wake_on_entry`: integers overriding §2 defaults.

## 16. Implementation Checklist
- [ ] Evaluate wake rolls before the cascade. Abort the turn if both fail.
- [ ] Enforce the cascade order and cracked-weapon adjustments from §§3–4.
- [ ] Limit conversions to picked-up (`origin == "world"`) items and honour the bag filter.
- [ ] Ignore broken placeholders during pickup scoring.
- [ ] Apply deterministic wear (`wear_amount = 5`) and crack handling per §6.
- [ ] Schedule armour removal and weapon drops as described in §7.
- [ ] Equip better weapons/armour immediately using the derived comparisons in §8.
- [ ] Apply level-relative courage modifiers (§9) and pursuit rules (§10).
- [ ] Grant the post-kill bonus action with the 25% pickup bias (§11).
- [ ] Keep innate attack messages per catalog entry while reusing the emote library (§§12–13).
