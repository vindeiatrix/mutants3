# AI & Combat System (v1)

**Changelog**
- 2025-05-06 – First consolidated specification of combat resolution, monster AI, and supporting data contracts.

---

## 1. Executive Summary & Scope
This document defines the end-to-end combat loop and monster artificial intelligence used in Mutants. It fuses the intent recorded in `docs/combat_system_notes.md` with the observed behaviours in the historical gamelogs. The specification covers:

- Data contracts for monsters, players, and combat-relevant items.
- The synchronous combat pipeline, including targeting, perception, hit resolution, damage, status handling, and loot/resource outcomes.
- Monster decision making: sensing, state machine, action selection, inventory etiquette, and respawn hooks.
- Text rendering and logging rules that recreate the cadence seen in archival logs.
- UX touchpoints (commands, prompts) that expose combat state to players.
- Worked examples that demonstrate how the system should play out end-to-end.

**Out of scope (future work):** non-combat quest scripting, overworld economy tuning, non-hostile NPC schedules, long-term persistence of world events outside combat, and multiplayer arbitration. These can be layered on top once the combat + AI foundation is stable.

## 2. Design Goals & Constraints
1. **Faithful recreation.** Match the tone, ordering, and side-effects observed in original logs (e.g., taunt-before-attack, "body is glowing" heals, skull drops). 【F:docs/combat_system_notes.md†L1-L85】【F:docs/gamelogs/2100wiz.txt†L70-L128】【F:docs/gamelogs/4600plus3hb.txt†L54-L152】
2. **Deterministic turns.** Combat resolves inside a single-threaded tick loop where every player input consumes one turn; monsters react synchronously. This matches the player's perception that even a mistyped command advances time. 【F:docs/combat_system_notes.md†L21-L59】
3. **Deterministic reproducibility.** All randomness must come from a seeded PRNG so that golden log tests can replay a fight bit-for-bit. The default seed is `RNG.seed_from_world(year, turn_number)`; tests inject a fixed seed.
4. **Performance target.** Resolve 100 concurrent monster instances with <2 ms per turn on commodity hardware. Optimise by caching derived stats and preloading catalogue data.
5. **Consistency across sessions.** Monster targeting persists even if the player plane-shifts years, unless the player dies or exits to the class menu. Monsters keep player loot after a kill. 【F:docs/combat_system_notes.md†L61-L85】
6. **Clarity in logs.** Every meaningful state change (target acquisition, heal, flee, drop) emits a line. "Screaming" ambience is allowed without consuming turns and can be throttled per monster to avoid spam. 【F:docs/gamelogs/2100wiz.txt†L128-L208】
7. **Safety valves.** When the field is saturated with items, subsequent drops evaporate, as seen in the logs. Preserve this to avoid infinite clutter. 【F:docs/combat_system_notes.md†L41-L59】【F:docs/gamelogs/4600plus3hb.txt†L160-L240】

## 3. Data Model (Runtime Contracts)
SQLite is the source of truth for catalogue and live-world state. JSON snapshots in `state/` mirror the same schema for offline tooling.

### 3.1 Monsters Catalogue (`monsters_catalog`)
Existing table is retained with additional indexing. All JSON columns use canonical JSON (UTF-8) with snake_case keys.

```sql
CREATE TABLE IF NOT EXISTS monsters_catalog (
    monster_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL CHECK(level > 0),
    hp_max INTEGER NOT NULL CHECK(hp_max > 0),
    armour_class INTEGER NOT NULL CHECK(armour_class >= 0),
    spawn_years TEXT NOT NULL,            -- JSON array of integers
    spawnable INTEGER NOT NULL DEFAULT 1,
    taunt TEXT NOT NULL,
    stats_json TEXT NOT NULL,             -- {"str":int,"int":int,"wis":int,"dex":int,"con":int,"cha":int}
    innate_attack_json TEXT NOT NULL,     -- see below
    exp_bonus INTEGER NOT NULL DEFAULT 0,
    ions_min INTEGER NOT NULL DEFAULT 0,
    ions_max INTEGER NOT NULL DEFAULT 0,
    riblets_min INTEGER NOT NULL DEFAULT 0,
    riblets_max INTEGER NOT NULL DEFAULT 0,
    spells_json TEXT NOT NULL DEFAULT '[]',
    starter_armour_json TEXT NOT NULL DEFAULT '[]',
    starter_items_json TEXT NOT NULL DEFAULT '[]',
    personality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS monsters_catalog_spawn_idx
    ON monsters_catalog(spawnable, level, armour_class);
```

`innate_attack_json` shape:
```json
{
  "name": "Hydraulic Slam",
  "power_base": 16,
  "power_per_level": 3,
  "line": "The Titan of Chrome crushes you with a hydraulic slam!",
  "damage_type": "bludgeoning",
  "status": {"id": "stun", "chance": 0.15, "duration_turns": 1}
}
```
- `line` is rendered via the innate attack formatter (§10.2).
- `power_base` and `power_per_level` plug into the damage formula (§6.2).
- `status` is optional. If omitted, no secondary effect applies.

### 3.2 Monster Instances (`monsters_instances`)
Live monsters require richer state to track targeting, AI mode, and inventory references.

```sql
CREATE TABLE IF NOT EXISTS monsters_instances (
    instance_id TEXT PRIMARY KEY,
    monster_id TEXT NOT NULL REFERENCES monsters_catalog(monster_id),
    year INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    hp_cur INTEGER NOT NULL,
    hp_max INTEGER NOT NULL,
    exhaustion INTEGER NOT NULL DEFAULT 0 CHECK(exhaustion BETWEEN 0 AND 100),
    armour_class INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'idle',     -- ai_state enum
    target_player_id TEXT,                  -- null when no player targeted
    target_instance_id TEXT,                -- allows monster-vs-monster in future
    statuses_json TEXT NOT NULL DEFAULT '[]',   -- [{"id":"poison","remaining":3,"intensity":2}]
    inventory_json TEXT NOT NULL DEFAULT '[]',   -- cached iid list for convenience
    wielded_iid TEXT,
    armour_iid TEXT,
    ions INTEGER NOT NULL DEFAULT 0,
    riblets INTEGER NOT NULL DEFAULT 0,
    last_action_tick INTEGER NOT NULL DEFAULT 0,
    ai_memory_json TEXT NOT NULL DEFAULT '{}',  -- e.g., cooldown timers
    created_at INTEGER NOT NULL CHECK(created_at >= 0)
);

CREATE INDEX IF NOT EXISTS monsters_at_idx
    ON monsters_instances(year, x, y, created_at, instance_id);

CREATE INDEX IF NOT EXISTS monsters_target_idx
    ON monsters_instances(target_player_id, year, created_at);
```

Migration (idempotent for existing DBs):
```sql
ALTER TABLE monsters_instances ADD COLUMN exhaustion INTEGER NOT NULL DEFAULT 0 CHECK(exhaustion BETWEEN 0 AND 100);
ALTER TABLE monsters_instances ADD COLUMN armour_class INTEGER NOT NULL DEFAULT 0;
ALTER TABLE monsters_instances ADD COLUMN state TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE monsters_instances ADD COLUMN target_player_id TEXT;
ALTER TABLE monsters_instances ADD COLUMN target_instance_id TEXT;
ALTER TABLE monsters_instances ADD COLUMN statuses_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE monsters_instances ADD COLUMN inventory_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE monsters_instances ADD COLUMN wielded_iid TEXT;
ALTER TABLE monsters_instances ADD COLUMN armour_iid TEXT;
ALTER TABLE monsters_instances ADD COLUMN ions INTEGER NOT NULL DEFAULT 0;
ALTER TABLE monsters_instances ADD COLUMN riblets INTEGER NOT NULL DEFAULT 0;
ALTER TABLE monsters_instances ADD COLUMN last_action_tick INTEGER NOT NULL DEFAULT 0;
ALTER TABLE monsters_instances ADD COLUMN ai_memory_json TEXT NOT NULL DEFAULT '{}';
```
Run each statement guarded by `PRAGMA table_info` checks to avoid duplicate columns.

### 3.3 Player Runtime View
Players remain primarily in JSON state files but the combat engine expects the following payload per active class:
```json
{
  "player_id": "player_wizard",
  "class": "Wizard",
  "level": 1,
  "hp": {"current": 23, "max": 23},
  "armour_class": 1,
  "stats": {"str":14, "int":17, "wis":17, "dex":13, "con":14, "cha":15},
  "wielded_iid": "iid-sling-sword",
  "armour_iid": null,
  "inventory": ["iid-sling-sword", "iid-mage-stick"],
  "statuses": [
    {"id":"exhaustion","remaining":0,"intensity":0}
  ],
  "ions": 120386,
  "riblets": 1480,
  "target_instance_id": "monster-uuid",   // null when not targeting
  "ready_spell": null,
  "exhaustion": 0,
  "position": {"year":2100, "x":6, "y":0}
}
```

### 3.4 Items
`items_instances` already stores weapon/armour condition. Combat requires:
- `condition`: 0–100, decremented by wear. 0 promotes the item to a `Broken-*` surrogate.
- `origin`: `native`, `world_spawn`, `monster_drop`, `player_drop`. Monsters may only convert items with origin `world_spawn` or `player_drop`.
- `owner`: `NULL` when on ground; player/monster id when carried.
- Additional virtual fields (computed in registries):
  - `derived.base_damage`
  - `derived.armour_class`
  - `derived.damage_type`
  - `derived.range_tiles`
  - `derived.is_ranged`
  - `derived.is_healing`

Broken items: once converted to `Broken-Weapon`/`Broken-Armour` the `damage` and `armour_class` drop to 0, and monsters immediately drop them (inventory rule §9.4).

### 3.5 Status Definitions
Provide a canonical registry (YAML or JSON) describing status IDs:
- `poison`: deals damage over time (`2 + floor(attacker.level / 3)` per turn), cleansed by `heal` command or `Dispel Magic` spell.
- `stun`: skips the next attack turn.
- `exhaustion`: tracked via exhaustion meter; at 100 the player emits "You're too exhausted to continue fighting!" and must rest or wait for it to tick down. 【F:docs/gamelogs/2100wiz.txt†L128-L184】
- Additional statuses can be appended.

## 4. Combat Pipeline
### 4.1 Turn Order & Timing
1. **Player command phase.** Every input (valid or gibberish) consumes a turn. After executing the command, increment `turn_number` and feed it into `RNG.seed_from_world` for deterministic monster reactions. 【F:docs/combat_system_notes.md†L21-L59】
2. **Monster reaction phase.** For the active room (current year/x/y) evaluate each monster in initiative order:
   - Monsters that share the tile with the active player resolve one AI tick.
   - Monsters in adjacent tiles may emit perception lines (shadows, footsteps, yelling) without consuming their turn (§5).
   - Monsters in pursuit across years queue their action so that when the player re-enters the shared year the monster acts immediately (travel counts as a turn). 【F:docs/combat_system_notes.md†L73-L85】
3. **Ambient phase.** Evaluate ambient audio/visual cues (screams, footsteps). This phase does not decrement cooldowns or change HP; it purely emits text so logs can interleave "You hear faint sounds of footsteps far to the east." between turns. 【F:docs/gamelogs/2100wiz.txt†L160-L224】
4. **Status tick.** Apply damage-over-time/heal-over-time and exhaustion recovery after the monster reaction phase.
5. **Cleanup.** Persist HP, ion, inventory changes, and log entries.

### 4.2 Initiative
- **Baseline:** Player acts, then monsters in the same tile act in catalogue order (sorted by `dex` descending, tie-break by `instance_id`).
- **PROPOSED – Surprise round:** On first contact (target acquisition) the monster may get an immediate free attack if `RNG(0,99) < 15`. This matches occasional rapid responses seen in logs where taunt and strike occur consecutively.

### 4.3 Targeting & Engagement
1. A monster or player must share a tile (`year`, `x`, `y`) to attempt targeting. Targeting consumes a turn.
2. Players issue `combat [name]` (prefix allowed). Monsters run `ai_decide` and, if they choose `AcquireTarget`, roll `targeting_check` (see pseudocode §8.3).
3. On success, set `target_*` fields, emit the taunt line, and (5% chance) append "{monster} is getting ready to combat you!". 【F:docs/combat_system_notes.md†L1-L35】【F:docs/gamelogs/2100wiz.txt†L86-L128】
4. On failure, no text is emitted when the player re-enters a monster-occupied tile from character select (per notes).
5. A monster/player may switch targets freely; the previous target is cleared automatically.
6. Leaving the game (class menu) or dying clears the player's outgoing target reference; monsters drop targeting upon death, player exit, or after 6 hours of in-game inactivity (PROPOSED safety valve).
7. When a targeted player shifts years without dying or exiting, the monster retains the target and reacts on the player's first turn back in the shared year. 【F:docs/combat_system_notes.md†L69-L85】

### 4.4 Opportunity Attacks
There are no opportunity attacks in the archival material; moving away simply grants the monster a chase opportunity on its next turn. This remains out of scope for v1 (documented to avoid assumptions).

## 5. Perception & Messaging
### 5.1 Visual Shadows
- Render "You see shadows to the {direction}." when a hostile monster occupies an orthogonally or diagonally adjacent tile. Trigger immediately when the monster enters adjacency and persist until it moves away. 【F:docs/combat_system_notes.md†L35-L59】【F:docs/gamelogs/2100wiz.txt†L96-L172】
- During pursuits, the player sees the shadow in the tile they just entered before the monster takes its movement turn.

### 5.2 Audio Cues
- **Range:** Maximum Manhattan distance 4 tiles.
- **Intensity:**
  - Distance 1 → "You hear loud sounds of ...".
  - Distance 2–3 → "You hear sounds of ...".
  - Distance 4 → "You hear faint sounds of ... far to the {direction}."
- **Event types:** `footsteps` when monsters move; `yelling and screaming` when they emit taunt or flee lines while not co-located. 【F:docs/gamelogs/2100wiz.txt†L160-L208】
- Audio emissions do not consume the monster's turn.

### 5.3 Screams & Taunts
- Taunt lines fire on successful targeting in the same turn as the target acquisition.
- Monsters may also emit freeform "screams" while fleeing ("{monster} screams: Get away from me, {player}!!!") without consuming their turn. Trigger when state transitions to `flee`. 【F:docs/gamelogs/2100wiz.txt†L208-L256】【F:docs/gamelogs/4600plus3hb.txt†L148-L200】

## 6. Hit Resolution
### 6.1 To-Hit Formula (PROPOSED)
Because the notes do not include explicit hit math, adopt a d100-based check tuned to logged hit frequency:
```text
hit_roll = RNG(1, 100)
attacker_bonus = attacker.level * 2 + floor(attacker.stats.dex / 5)
defender_threshold = 40 + defender.armour_class / 2
```
- If `hit_roll + attacker_bonus >= defender_threshold`, the attack hits.
- Natural 1 (`hit_roll == 1`) always misses (fumble). Emit "{monster} fumbles!" (PROPOSED future flavour).
- Natural 100 (`hit_roll == 100`) always hits and counts as a critical.
- Criticals multiply post-mitigation damage by 1.5 (rounded). (PROPOSED; no evidence in logs yet, but allows design flexibility.)
- Log misses with "{attacker} swings wildly at {target}!" (PROPOSED default until archival evidence arrives).

### 6.2 Damage Calculation
1. **Base damage:**
   - Weapons: `item.derived.base_damage + floor(attacker.stats.str / 10)`.
   - Ranged bolts: use the weapon's base bolt damage; apply same STR bonus unless flagged `dex_bonus` (then use DEX).
   - Innate attacks: `innate.power_base + innate.power_per_level * attacker.level`.
2. **Armour mitigation:** For every +10 armour class, subtract 3.15 damage. Compute `mitigation = round((defender.armour_class / 10) * 3.15)`. Damage cannot drop below 0. 【F:docs/combat_system_notes.md†L85-L100】【F:docs/gamelogs/2900goldchunk.txt†L1-L120】
3. **Status modifiers:**
   - `poisoned` defender takes +2 flat damage from melee.
   - `stunned` defender cannot dodge.
4. **Resistances/Vulnerabilities (PROPOSED):** Add optional per-monster arrays `resists` / `weaknesses`. For now default to none.
5. **Final damage:** `(base_damage - mitigation) * crit_multiplier` (floor at 0). Apply to HP and log "You suffer N hit points of damage!" when the player is the defender. When damage reduces HP to 0 or below, trigger death pipeline (§7).

### 6.3 Exhaustion & Command Links
- Every damaging player command (`wield` strike, spells, convert) adds exhaustion based on item weight: `ceil(item.weight / 2)`.
- Exhaustion over 100 prevents further attacks (emit "You're too exhausted to continue fighting!") until it decays by 10 per rest turn.
- Monster exhaustion increases at half rate; they don't log exhaustion warnings (no evidence in logs).

## 7. Effects, Healing, and Resource Changes
### 7.1 Healing
- **Player `heal` command:** Restores `level + 5` HP. Costs ions per level: Warrior/Priest 750, Mage 1200, Wizard 1000, Thief 200. Deduct ions, emit "Your body glows as it heals X points!" and, if HP already full, append "You're healed to the maximum!". 【F:docs/combat_system_notes.md†L11-L29】【F:docs/gamelogs/2100wiz.txt†L144-L220】
- **Monster heal:** Modeled after Thief cost: heal `level + 5` HP, cost `200 * level` ions. Emit "{monster}'s body is glowing!" (no amount shown). Monsters attempt healing when in `heal` state (§9.3).
- Healing triggers DoT cleanup for `poison` on the actor.

### 7.2 Status Application
Use `apply_status(target, effect)` pseudocode (§8.2) to stack statuses. Rules:
- Duplicate status refreshes duration if new intensity >= existing.
- `poison` ticks during status phase for `effect.intensity` turns.
- `stun` toggles a `skip_next_attack` flag consumed on the next attack opportunity.

### 7.3 Death & Loot
1. **Death check:** On HP ≤ 0 call `handle_death(victim, killer)`.
2. **Monster death:**
   - Transfer XP, ions, riblets to killer per catalogue ranges; log in the order observed: XP, riblets/ions, drop lines, "{monster} is crumbling to dust!". 【F:docs/combat_system_notes.md†L41-L59】【F:docs/gamelogs/4600plus3hb.txt†L144-L208】
   - Drop carried items in this order: inventory items (latest picked first), guaranteed skull (`A Skull is falling...`), worn armour last. Respect ground capacity (max 12 items PROPOSED); excess items are deleted with no log to match archival behaviour.
3. **Player death:**
   - Killer monster loots all player's ions/riblets (persist on monster instance).
   - Player respawns at year 2000 (0,0) with full HP, zero exhaustion, empty target, and inventory intact (unless future penalty is defined). 【F:docs/combat_system_notes.md†L41-L59】
   - Emit placeholder lines: "You have been defeated!" + "You awaken in year 2000." (PROPOSED messaging).

### 7.4 Resource Hooks
- Award XP before loot to align with logs.
- Update player's `ready_target` to `None` after kill.
- Notify spawn manager so replacement monsters can hatch after 1–5 minutes real-time (PROPOSED to match "egg is hatching" cadence). 【F:docs/gamelogs/2900goldchunk.txt†L1-L80】

## 8. Core Algorithms (Pseudocode)
### 8.1 `resolve_attack(attacker, defender, context)`
```python
def resolve_attack(attacker, defender, context):
    rng = context.rng
    attack_payload = attacker.pick_attack_source(context)
    hit_roll = rng.randint(1, 100)
    attacker_bonus = attacker.level * 2 + attacker.stats.dex // 5
    defender_threshold = 40 + defender.armour_class / 2

    if hit_roll == 1:
        log.fumble(attacker, defender)
        return AttackResult(missed=True)

    if hit_roll != 100 and hit_roll + attacker_bonus < defender_threshold:
        log.miss(attacker, defender)
        return AttackResult(missed=True)

    crit = hit_roll == 100
    base_damage = attack_payload.base_damage(attacker)
    mitigation = round((defender.armour_class / 10) * 3.15)
    damage = max(0, base_damage - mitigation)
    if crit:
        damage = math.floor(damage * 1.5)

    defender.hp_cur -= damage
    if defender.is_player:
        log.player_damage(defender, damage)
    else:
        log.monster_damage(defender, damage)

    for effect in attack_payload.status_effects:
        apply_status(defender, effect, context)

    if defender.hp_cur <= 0:
        handle_death(defender, attacker, context)

    wear.apply_on_hit(attacker, attack_payload, context)
    return AttackResult(missed=False, crit=crit, damage=damage)
```

### 8.2 `apply_status(target, effect, context)`
```python
def apply_status(target, effect, context):
    existing = target.statuses.get(effect.id)
    if existing and existing.intensity >= effect.intensity:
        existing.remaining = max(existing.remaining, effect.duration)
    else:
        target.statuses[effect.id] = StatusState(
            id=effect.id,
            intensity=effect.intensity,
            remaining=effect.duration,
        )
    log.status_applied(target, effect)
```

### 8.3 `ai_decide(monster, context)`
The AI uses a deterministic state machine evaluated every monster turn (unless stunned).

```python
def ai_decide(monster, context):
    update_perception(monster, context)

    if monster.state == 'stun':
        monster.state = 'idle'
        log.stunned(monster)
        return

    state = monster.state
    transitions = AI_STATE_MACHINE[state]
    for transition in transitions:
        if transition.condition(monster, context):
            monster.state = transition.next_state
            transition.on_enter(monster, context)
            break

    ACTIONS[monster.state](monster, context)
```

`AI_STATE_MACHINE` and `ACTIONS` are defined in §9.3.

## 9. Monster AI
### 9.1 Sensing & Aggro Acquisition
- **Vision:** Monsters detect targets in the same tile; adjacency only yields shadows. Monsters do not attack through walls.
- **Hearing:** Monsters can be scripted to respond to loud events (PROPOSED future). Not required for v1.
- **Taunt timing:** When transitioning into `pursue` with no existing target, the monster taunts first, then—if RNG < 5—emits the "is getting ready" line. Attack decisions are evaluated on the following tick to mirror logs where taunt precedes the first hit. 【F:docs/combat_system_notes.md†L1-L35】【F:docs/gamelogs/2100wiz.txt†L86-L128】

### 9.2 State Machine Overview
| State | Description | Transitions |
|-------|-------------|-------------|
| `idle` | Monster is stationary, no target. | `DetectTarget` → `taunt`; `PlayerInAdjacency` → `patrol`; `AmbientScream` → `idle` (no cost). |
| `patrol` | Monster roaming spawn radius. | `SeesPlayer` → `taunt`; `TimerExpired` → `idle`. |
| `taunt` | Acquire target, emit taunt. | After taunt → `pursue`. |
| `pursue` | Chase target across tiles/years. | `SameTileAsTarget` → `attack`; `LostSight` → `patrol`; `LowHP` → `flee`. |
| `attack` | Evaluate attack vs heal vs loot priorities. | `LowHP` → `flee`; `TargetDead` → `idle`; `WeaponBroken` → `reequip`; `TargetOutOfTile` → `pursue`. |
| `heal` | Spend ions to recover HP (body glow). | When HP ≥ threshold → `attack`. |
| `reequip` | Evaluate inventory for better gear. | After action → `attack`. |
| `loot` | Pick up ground items respecting filters. | After action → `attack`. |
| `flee` | Move away, emit flee scream. | `SafeDistance` → `patrol`; `HPRecovered` → `pursue`; `Trapped` → `attack`. |

Evaluation interval: each monster tick (once per player command). Cooldowns stored in `ai_memory_json` (e.g., `taunt_cooldown`, `heal_cooldown`).

### 9.3 Transition Rules & Thresholds
- `DetectTarget`: if player shares tile and `RNG(1,100) <= 85` (monsters usually engage). Failure means monster stays idle that tick.
- `LowHP`: `hp_cur <= 0.25 * hp_max` triggers `flee`. Matches logs where monsters scream and run at low health. 【F:docs/gamelogs/2100wiz.txt†L224-L288】
- `HealPreference`: while `hp_cur <= 0.6 * hp_max` and ions ≥ cost, monster may enter `heal` once every 4 turns (cooldown).
- `Reequip`: triggered when `weapon.condition <= 0` or ground item significantly better (damage +5 or more). Monster drops broken gear immediately. 【F:docs/gamelogs/4600plus3hb.txt†L200-L240】
- `Loot`: triggered if no target or during attack downtime (<25% chance) and there is non-broken loot.
- `Flee`: move in opposite direction from player; emit "{monster} screams: Get away from me, {player}!!!" once per transition. If path blocked, fallback to `attack` next tick.
- `Pursuit across years`: if player plane-shifts, mark `pending_action='pursue'`. On player's next turn in shared year, monster resolves `pursue` immediately. 【F:docs/combat_system_notes.md†L69-L85】

### 9.4 Inventory Etiquette
- Never convert native starter gear (`origin='native'`).
- Never pick up `Broken-*` items. 【F:docs/combat_system_notes.md†L1-L35】【F:docs/gamelogs/4600plus3hb.txt†L200-L240】
- Drop broken armour immediately; drop broken weapons on the same or next tick.
- Prefer higher damage weapons and higher AC armour.
- Do not convert equipped armour/weapons mid-fight.
- Monsters can pick up skulls (logs show this). They may convert skulls later if not native.

### 9.5 Spawner Hooks
- **Initial spawn:** `scripts/monsters_initial_spawn.py` seeds monsters per `spawn_years`. Each spawn stores `created_at` epoch milliseconds.
- **Top-ups:** Every in-game year, the spawner checks if population density < target and may hatch eggs after 1–5 minutes (random). Emit "You notice an egg is hatching!" in the local room when spawn occurs. 【F:docs/gamelogs/2900goldchunk.txt†L1-L80】
- **Death → respawn:** After `handle_death`, schedule a respawn timer (catalog-driven, PROPOSED default 10–20 minutes). Monsters respawn in a spawn tile with default loadout and zero targets.

## 10. Text Rendering & Logging
### 10.1 Taunts & Combat Lines
- Use monster catalogue `taunt` string when acquiring target. Template supports `{monster}` and `{player}` tokens for substitution.
- Additional ready line triggered with 5% probability: "{monster} is getting ready to combat you!". 【F:docs/combat_system_notes.md†L1-L35】【F:docs/gamelogs/2100wiz.txt†L86-L128】

### 10.2 Innate Attack Formatter
- Source: `monsters_catalog.innate_attack_json.line`.
- Formatter tokens: `{monster}`, `{attack}`, `{target}`.
- Example: template `"The {monster} bites poison into {target}!"` renders as "The Umber-Hulk-1228 bites poison into you!". 【F:docs/gamelogs/4600plus3hb.txt†L104-L132】

### 10.3 Logging Order Examples
- Attack from player: `"You've hit {monster} with your {weapon}!"` followed by defender reaction (heal, scream, damage).
- Attack from monster: `"{monster} has hit you with {his/her} {weapon}!"` then "You suffer N hit points of damage!".
- Heal: `"{actor}'s body is glowing!"` (monsters) or `"Your body glows as it heals X points!"` (player). 【F:docs/gamelogs/2100wiz.txt†L96-L208】
- Conversion: `"You see a blinding white flash illuminate from {monster}'s body!"` when a monster converts loot (inferred from repeated flashes followed by no loot on ground). 【F:docs/gamelogs/test1.txt†L25-L120】
- Death drop: `"A {Item} is falling from {monster}'s body!"` for each item that successfully lands, respecting order (inventory, skull, armour). 【F:docs/gamelogs/4600plus3hb.txt†L148-L200】

## 11. Commands & UX Touchpoints
- `look`: renders room description, compass, ground items, shadows. Must also show immediate arrivals ("{monster} has just arrived from the west."). 【F:docs/gamelogs/2100wiz.txt†L160-L224】
- `stat`: displays player stats including `Ready to Combat` field. Update after every targeting change. 【F:docs/gamelogs/2100wiz.txt†L64-L120】
- `combat [target]`: attempts to acquire target; on success prints "You're ready to combat {monster}!".
- `wield [item]`: When a target is set, doubles as an attack command (legacy behaviour). Emit `"You've hit {monster} with your {item}!"` when the weapon is currently wielded, otherwise treat as equip (PROPOSED bridging mechanic to match logs where `wie` both equips and swings).
- `heal`: as detailed in §7.1; reject if insufficient ions with "You do not have enough ions.".
- `travel [year]`: counts as a turn; if already in target year emit "You're already in the 22th Century!" etc. 【F:docs/gamelogs/2100wiz.txt†L136-L176】
- `last`: repeats previous command; still consumes a turn (logs show repeated `last` with "You're king!"). 【F:docs/gamelogs/test1.txt†L33-L120】
- `mon`: (PROPOSED) displays monsters targeting the player and chance-to-hit preview using current weapon vs target AC. Example output: `"Lizard-Man-1683 – 58% to hit with Sling-Sword (avg dmg 4)."`

### Error Messaging & Edge Cases
- Attempting to target when no monster present: "There's nobody here by that name." (PROPOSED).
- Trying to heal at full HP: still emits heal message plus "You're healed to the maximum!" as per logs. 【F:docs/gamelogs/2100wiz.txt†L136-L220】
- Picking up broken gear: "You leave the broken remains alone." (monsters silently skip per AI rules).

## 12. Worked Examples
Each trace references archival logs to validate ordering.

### 12.1 Early Wizard vs Lizard-Man (2100)
1. Player uses `combat l` → `You're ready to combat Lizard-Man-1683!`.
2. Monster enters `taunt` state, emits `"The Lizard-Man-1683 hisss: You'd make a good meal, Vindy!"` then 5% chance ready line (triggered in log). 【F:docs/gamelogs/2100wiz.txt†L96-L136】
3. Monster transitions to `attack`; small-spear strike resolves: hit for 7 damage after mitigation (base 10 − armour). 【F:docs/gamelogs/2100wiz.txt†L108-L136】
4. Player spams `wield sling-sword` hitting for 6–8 damage; exhaustion climbs to 100 leading to "You're too exhausted to continue fighting!". 【F:docs/gamelogs/2100wiz.txt†L160-L224】
5. Monster heals twice (`body is glowing`) spending ions (`200 * level`).
6. Player flees east; shadows + footsteps render as monster pursues, aligning with perception rules. 【F:docs/gamelogs/2100wiz.txt†L160-L240】

### 12.2 High-Level Mage vs Umber-Hulk (4600)
1. Monster innate attack triggers on first contact: `"The Umber-Hulk-1228 bites poison into you!"` applying `poison` status and 6 immediate damage. 【F:docs/gamelogs/4600plus3hb.txt†L96-L132】
2. Player attacks repeatedly with Hell-Blade; armour crack events log (`"...has just cracked down the center!"`).
3. Monster weapon cracks, switches to broken weapon, damage drops to 0 but still logs hits.
4. Monster flees at low HP, screaming line fired.
5. Player lands killing blow; logs show XP, riblets/ions, skull drop, monster crumbles in that order. 【F:docs/gamelogs/4600plus3hb.txt†L144-L200】

### 12.3 Silver Dragon Encounter (2900)
1. Monster taunts immediately upon sight then attacks despite player's heavy armour; weapon cracks on first hit demonstrating armour mitigation. 【F:docs/gamelogs/2900goldchunk.txt†L64-L120】
2. Player targets and strikes with Gold-Chunk; monster heals twice (`body is glowing`).
3. Monster's broken weapon still attempts to hit (0 damage), satisfying AI rule to drop broken items soon after.
4. No loot falls mid-fight; spec emphasises drop order only on death.

### 12.4 Monster Conversion Flash (Test1)
1. Thief-242 picks up ion pack and skull.
2. Flash occurs (`"You see a blinding white flash illuminate from Thief-242's body!"`) indicating conversion of held item to ions. 【F:docs/gamelogs/test1.txt†L21-L88】
3. Monster attacks with Gold-Chunck multiple times, consistent with AI continuing attack state despite conversion.

### 12.5 Pursuit Across Years
1. Player flees into another year; targeted monster remains flagged.
2. Upon re-entering year, immediate arrival message logs and monster attacks on same turn, matching `travel` counting as a turn. 【F:docs/combat_system_notes.md†L69-L85】

## 13. Implementation Plan
### Milestones
- **M0 – Schema & Validation**
  - Add new columns to `monsters_instances` (migration script in `scripts/migrations/20250506_combat.sql`).
  - Extend catalogue loader to validate innate attack JSON schema.
  - Tests: schema migration unit tests, catalogue validation tests.

- **M1 – Combat Core**
  - Implement `resolve_attack`, mitigation, status engine, heal command.
  - Integrate exhaustion and RNG seeding.
  - Tests: unit tests for to-hit, mitigation, heal ion costs, armour crack progression; golden log reproduction for 2100 fight.

- **M2 – AI State Machine & Sensing**
  - Build AI transitions, pursuit across years, flee/heal behaviours.
  - Add perception outputs (shadows, footsteps, yelling).
  - Tests: AI state unit tests, integration test for flee threshold, adjacency messaging snapshot tests.

- **M3 – Logging & UX**
  - Wire text formatter for taunts/innate attacks, command outputs (`mon`, `heal`, `travel`).
  - Implement ambient audio scheduler.
  - Tests: golden-log diff tests against curated transcripts from `docs/gamelogs/`.

- **M4 – Balancing Knobs**
  - Expose config for to-hit thresholds, flee percentages, heal cooldowns.
  - Populate `personality_json` with species-specific nudges.
  - Tests: property tests ensuring config toggles stay within safe bounds.

### Testing Strategy
- Seedable RNG with `set_seed(12345)` for deterministic tests.
- Unit tests for data transforms (`stats_json` parsing, innate attack formatter).
- Integration tests simulating multi-turn combat, verifying log order via golden files.
- Load tests: script to simulate 100 monsters to ensure performance target.

## 14. Open Questions
1. **Critical hits evidence (OPEN).** No direct mention in notes/logs. Default multiplier 1.5 is PROPOSED; confirm with designer.
2. **Conversion flash meaning (OPEN).** Assumed to be ion conversion; verify if alternate effect exists.
3. **Ground capacity limit (OPEN).** Logs imply a cap but exact number unknown. PROPOSED 12; confirm.
4. **Player death messaging (OPEN).** Placeholder copy pending official flavour text.
5. **Wield-as-attack semantics (OPEN).** Logs show `wie` both equips and attacks; confirm whether separate `attack` command should exist or if this dual-use is canonical.
6. **Spawn egg timing (OPEN).** Notes mention 1–5 minutes; implement as PROPOSED but confirm distribution.

---

This specification is the authoritative reference for engineering the AI & Combat System v1. All future changes should append to the changelog with rationale and links to validating logs or design notes.
