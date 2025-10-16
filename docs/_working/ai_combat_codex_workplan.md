# AI & Combat System — Implementation Workplan (Codex-ready)

## Executive Summary
- **Goal:** deliver a synchronous combat loop with deterministic initiative ticks and a feature-complete monster AI that matches archival MajorBBS behaviour for targeting, taunts, sensory feedback, loot, and equipment wear. The loop must support both player-issued commands and AI decisions inside a shared tick engine.
- **Out of Scope (current phase):** world map generation changes, new player classes, long-term progression tuning, network/multi-user infrastructure, and live balancing automation beyond seedable simulations. PvP combat hooks are deferred; only PvE interactions are covered here.

## Current State Inventory

### Module Map (relevant excerpts)
| Area | Key Modules | Notes |
| --- | --- | --- |
| Command parsing & dispatch | `src/mutants/commands/combat.py`, `strike.py`, `wield.py`, `look.py`, `convert.py`, `register_all.py` | Combat targeting already exists (`combat_cmd` prepares `ready_target` and pushes feedback). `strike_cmd` handles player damage, loot minting, and logging but lacks turn gating and AI responses.【F:src/mutants/commands/combat.py†L1-L101】【F:src/mutants/commands/strike.py†L1-L213】 |
| Bootstrap/runtime | `src/mutants/bootstrap/lazyinit.py`, `validator.py`, `runtime.py` | Lazy loaders hydrate JSON/SQLite state; validator enforces schema consistency on startup.
| Services (combat/AI) | `src/mutants/services/monster_actions.py`, `damage_engine.py`, `monsters_state.py`, `combat_loot.py`, `monster_spawner.py` | Monster action helpers exist but currently act as utility library; no wake/cascade logic, cracked-gear drop stubs, or initiative scheduler. `damage_engine.resolve_attack` subtracts AC from base power with no hit roll or status pipeline.【F:src/mutants/services/monster_actions.py†L1-L160】【F:src/mutants/services/damage_engine.py†L1-L120】 |
| Registries & persistence | `src/mutants/registries/sqlite_store.py`, `monsters_instances.py`, `items_instances.py`, `monsters_catalog.py` | SQLite migration scaffolding creates `items_instances`, `monsters_instances`, catalog tables, and indices but stores limited monster runtime fields (no bag, ai_state, or target persistence columns).【F:src/mutants/registries/sqlite_store.py†L526-L615】 |
| Rendering & logging | `src/mutants/ui/renderer.py`, `ui/logsink.py`, `ui/feedback.py`, `debug/turnlog.py` | Feedback bus pushes message topics; turnlog captures structured combat events. Formatting helpers exist for items/monsters.
| Data access & state | `src/mutants/services/player_state.py`, `monsters_state.py`, `state.py`; JSON snapshots under `state/` | Player live state stored in `playerlivestate.json` (stats, inventory, target stubs). Monsters catalog lives in JSON; live instances rely on registries/SQLite when running. Example player entry shows `target_monster_id` placeholder with `None`.【F:state/playerlivestate.json†L1-L40】 |

### Existing DB / Schema Snapshot
- **items_instances**: columns `(iid PK, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at)` with indices on `(year,x,y,created_at,iid)`, `(owner,created_at,iid)`, and `(origin)`. Stores all world and inventory item instances.【F:src/mutants/registries/sqlite_store.py†L526-L566】
- **monsters_instances**: `(instance_id PK, monster_id, year, x, y, hp_cur, hp_max, stats_json, created_at)` plus `(year,x,y,created_at,instance_id)` index. Needs extensions for AI state, bag, target, and timers.【F:src/mutants/registries/sqlite_store.py†L546-L563】
- **items_catalog / monsters_catalog**: catalog metadata with JSON blobs for derived stats, spells, starter gear, innate attack lines, etc.【F:src/mutants/registries/sqlite_store.py†L568-L603】
- **runtime_kv**: generic key/value persistence for runtime knobs (suitable for storing RNG seeds, cascade offsets).
- **players**: only created in tests; production bootstrap needs migration for wield/armour references to coordinate with inventory cleanup.【F:tests/services/test_player_reset.py†L22-L83】

### Feature Checklist
| Feature | Status | Notes |
| --- | --- | --- |
| Player targeting (`combat` command) | ✅ Implemented | Sets ready target and feedback messaging, but no monster-side state update or initiative impact.【F:src/mutants/commands/combat.py†L42-L101】 |
| Player strike damage | ⚠️ Partial | `strike_cmd` handles damage, wear, loot, and kill messaging, but lacks to-hit RNG, turn order, AC mitigation curve (uses simple subtraction), status, and monster retaliation.【F:src/mutants/commands/strike.py†L214-L308】 |
| Monster AI cascade | ❌ Missing | `monster_actions` contains helpers (pickup scoring, convert value, wear handling) but no wake/tick driver or decision pipeline.【F:src/mutants/services/monster_actions.py†L1-L120】 |
| Taunts & combat text | ⚠️ Partial | Catalog taunts exist; `strike` emits simple lines. Monster taunt timing, “getting ready” variant, and innate attack strings are not wired into gameplay.【F:docs/combat_system_notes.md†L1-L40】【F:docs/monster_ai_spec.md†L96-L140】 |
| Shadows / audio cues | ❌ Missing | No implementation for adjacent shadow lines or distant yelling/hearing system from notes.【F:docs/combat_system_notes.md†L41-L76】 |
| Heal command | ❌ Missing | No command file or player ion cost logic for healing per level/class.【F:docs/combat_system_notes.md†L10-L24】 |
| Monster healing | ❌ Missing | AI does not evaluate heals; heal visuals absent.【F:docs/combat_system_notes.md†L24-L33】【F:docs/monster_ai_spec.md†L52-L90】 |
| Armour mitigation curve | ⚠️ Partial | Current `damage_engine` subtracts total AC linearly; spec requires 3.15 damage reduction per +10 AC rounding behaviour.【F:docs/combat_system_notes.md†L92-L93】【F:src/mutants/services/damage_engine.py†L200-L263】 |
| Death/loot ordering | ⚠️ Partial | Player strikes spawn loot but not in required order (carried, skull, worn). Player death flow/respawn unimplemented.【F:docs/combat_system_notes.md†L77-L91】 |
| Spawners & persistence | ⚠️ Partial | Monster spawner controller exists but lacks hooks for death/respawn, target persistence across years, or cracked gear drops.【F:src/mutants/services/monster_spawner.py†L229-L392】 |

### Gaps vs. Requirements (Docs)
- Wake triggers, cascade thresholds, cracked weapon bias, ion economy gates, pursuit modifiers, emote library, and post-kill bonus action from `monster_ai_spec.md` are absent.
- Combat notes require heal command, monster heal costs aligned with class economics, taunt/tell text timing, sensory cues (shadows, audio), death handling, cross-year targeting persistence, and AC mitigation adjustments—all missing or incomplete.
- Schema lacks persistence for `_ai_state`, bag contents, target tracking, pursuit timers, and respawn scheduling needed by the AI specification.
- Logging needs explicit strings (attack, heal, convert, taunt, death) with placeholders; current bus messages differ from archival requirements.
- Need deterministic turn scheduler to ensure “every action is a turn,” including invalid commands, with special-case entry handling per notes.

## Traceability Matrix
| Req ID | Description | Source | Planned Tasks |
| --- | --- | --- | --- |
| C1 | Monster taunt immediately on target plus 5% “getting ready” line | combat_system_notes.md | “Monster Taunt & Ready Messaging Hook”, “Feedback Templates Audit” |
| C2 | Default player name `Vindeiatrix` until names exist | combat_system_notes.md | “Player Name Default Wiring” |
| C3 | Heal command: level+5 HP, ion cost per class | combat_system_notes.md | “Player Heal Command Implementation”, “Heal Cost Validation & Logging” |
| C4 | Monsters heal using Thief cost/amount | combat_system_notes.md | “Monster Heal Gate Integration” [CONFLICT], “Monster Ion Ledger Sync” |
| C5 | Every input consumes a turn | combat_system_notes.md | “Turn Scheduler Core Loop”, “Invalid Command Turn Accounting” |
| C6 | Entry from class menu allows monster target roll only | combat_system_notes.md | “Login Entry Target Roll Guard” |
| C7 | Targeting rules same for players/monsters; single target; resets | combat_system_notes.md | “Target Persistence Schema Upgrade”, “Target Reset Hooks” |
| C8 | Monster taunt on targeting, resets on exit/death | combat_system_notes.md | “Monster Taunt & Ready Messaging Hook”, “Target Reset Hooks” |
| C9 | Shadow lines for adjacent monsters | combat_system_notes.md | “Shadow Renderer Integration” |
| C10 | Hearing yelling/footsteps up to 4 tiles with far qualifiers | combat_system_notes.md | “Audio Cue Propagation Service” |
| C11 | Monster death loot order & ground overflow deletes | combat_system_notes.md | “Monster Loot Ordering Routine”, “Ground Capacity Check” |
| C12 | Player death respawn at 2000,0,0; transfer ions/riblets to killer | combat_system_notes.md | “Player Death Placeholder Handler”, “Monster Ion Ledger Sync” |
| C13 | Monster target persists across years until player dies/exits | combat_system_notes.md | “Target Persistence Schema Upgrade”, “Cross-Year Target Wake Hook” |
| C14 | Returning to targeted monster triggers immediate action | combat_system_notes.md | “Cross-Year Target Wake Hook”, “Turn Scheduler Core Loop” |
| C15 | Monster yelling/screaming doesn’t cost turn | combat_system_notes.md | “Emote Free Action Scheduler” |
| C16 | After targeting then wielding, strike should land | combat_system_notes.md | “Auto-Strike After Wield Ready” |
| C17 | Armour mitigation: every +10 AC cuts 3.15 damage (rounded) | combat_system_notes.md | “Mitigation Curve Implementation” |
| A1 | Wake rolls on LOOK/ENTRY with overrides | monster_ai_spec.md | “Wake Trigger Service” |
| A2 | Priority cascade gates with cracked bias | monster_ai_spec.md | “Cascade Evaluator Implementation”, “Cracked Bias Adjustments” |
| A3 | Attack type weighting incl. prefers_ranged | monster_ai_spec.md | “Attack Weight Resolver” |
| A4 | Ion economy: conversions, heal cost, cast cost, low-ion bias | monster_ai_spec.md | “Monster Heal Gate Integration” [CONFLICT], “Convert Eligibility Enforcement”, “Casting Gate Logic” |
| A5 | Deterministic wear application (amount=5) | monster_ai_spec.md | “Wear Application Harmonization” |
| A6 | Broken equipment drop scheduling | monster_ai_spec.md | “Broken Gear Drop Scheduler” |
| A7 | Pickup filters, upgrades, infinite carry | monster_ai_spec.md | “Pickup Filtering & Scoring Update”, “Auto-Equip Upgrade Hook” |
| A8 | Flee modifiers (HP %, cracked, level diff) | monster_ai_spec.md | “Flee Decision Logic” |
| A9 | Pursuit roll with modifiers and path fallback | monster_ai_spec.md | “Pursuit Behaviour Implementation” |
| A10 | Post-kill bonus cascade | monster_ai_spec.md | “Post-Kill Bonus Action Hook” |
| A11 | Combat text templates | monster_ai_spec.md | “Feedback Templates Audit” |
| A12 | Emote library 20 lines | monster_ai_spec.md | “Emote Library Wiring” |
| A13 | Species-specific nudges | monster_ai_spec.md | “Species Hint Loader” |
| A14 | No schema change required; runtime hints only | monster_ai_spec.md | “Monster Config Overrides Loader” |
| A15 | Checklist coverage QA | monster_ai_spec.md | “AI Checklist Verification Tests” |

> **[CONFLICT]** between C4 and A4 heal costs: notes demand `200 ions/level` cost and `level+5 HP` per heal, while AI spec prescribes flat 5 ions for 15% HP. **[PROPOSED]** resolution: adopt player-notes economics (Thief-style cost & level+5 HP) for both players and monsters, expose knobs in combat config so designers can emulate flat costs later if desired.

## Milestones (Phased Delivery)
- **M0 – Foundations & Migrations:** establish combat configuration, extend persistence (targets, ai_state, timers), seedable RNG plumbing, validators.
- **M1 – Core Combat Loop:** introduce tick/initiative scheduler, to-hit + mitigation, status scaffolding, heal command, invalid-turn accounting.
- **M2 – Monster AI:** implement wake triggers, cascade gates, cracked gear bias, ion economy, flee/pursuit, broken equipment handling, species hints.
- **M3 – Text & UX:** wire taunts, innate attack lines, sensory cues (shadows/audio), heal/convert logs, emotes, command surfaces.
- **M4 – Spawners/Death/Respawn Hooks:** enforce loot order, respawn placeholder, drop/XP transfers, cross-year targeting & immediate actions, stub future spawner/death flows.
- **M5 – Testing & Balancing:** golden logs, deterministic simulations, checklist verification, tuning knobs documentation.

## Task Backlog (Codex-consumable units)
---
Task Title
: Baseline Combat Config Module

Why / Outcome
: Centralize combat knobs (wake odds, gate thresholds, RNG seeds) with override support for future tuning.

Changes
: `src/mutants/services/combat_config.py` [new], `src/mutants/env.py`, `src/mutants/bootstrap/lazyinit.py`

APIs & Data
: Provide `CombatConfig load_combat_config(*, state_dir: str) -> CombatConfig` returning dataclass with defaults and override path.

Acceptance Criteria
: Config loader returns defaults from spec when no overrides exist; logs info on overrides; accessible via service registry.

Tests
: Unit test in `tests/services/test_combat_config.py` verifying defaults and override resolution.

Dependencies
: None

Complexity
: M

Notes
: [ASSUMPTION] Config stored as JSON under `state/config/combat.json`.
---
Task Title
: Schema Migration for Target & AI State

Why / Outcome
: Persist monster target IDs, ai_state, bag payloads, and pursuit timers to survive restarts.

Changes
: `src/mutants/registries/sqlite_store.py`, new migration file `scripts/migrations/v5_combat_state.py`

APIs & Data
: SQL:
  ```sql
  ALTER TABLE monsters_instances ADD COLUMN target_player_id TEXT;
  ALTER TABLE monsters_instances ADD COLUMN ai_state_json TEXT;
  ALTER TABLE monsters_instances ADD COLUMN bag_json TEXT;
  ALTER TABLE monsters_instances ADD COLUMN timers_json TEXT;
  CREATE INDEX IF NOT EXISTS monsters_target_idx ON monsters_instances(target_player_id);
  ```

Acceptance Criteria
: Migration idempotent, recorded in schema_meta, existing rows get NULL defaults.

Tests
: Migration unit test using in-memory SQLite verifying columns/indices.

Dependencies
: Baseline Combat Config Module

Complexity
: M

Notes
: [PROPOSED] timers_json holds wake cooldowns and pursuit debt.
---
Task Title
: Player Target Persistence Wiring

Why / Outcome
: Ensure player state exposes target fields for each class and resets consistently.

Changes
: `src/mutants/services/player_state.py`, `src/mutants/bootstrap/validator.py`

APIs & Data
: Extend player schema to include `target_monster_id` per active class; validator enforces string-or-null.

Acceptance Criteria
: Loading state sets default `None`; clearing target updates JSON snapshot.

Tests
: Player state round-trip test ensuring target persists and resets on exit.

Dependencies
: Schema Migration for Target & AI State

Complexity
: S

Notes
: —
---
Task Title
: Runtime RNG Seed Registry

Why / Outcome
: Allow deterministic combat simulations and golden logs.

Changes
: `src/mutants/services/random_pool.py` [new], `src/mutants/env.py`, `src/mutants/util/__init__.py`

APIs & Data
: Provide `get_rng(name: str) -> random.Random` seeded via `runtime_kv` (stores seed + tick counter).

Acceptance Criteria
: RNG identical across runs when seed provided; seed updated via helper to advance ticks.

Tests
: Unit test verifying reproducible sequences and persistence.

Dependencies
: Baseline Combat Config Module

Complexity
: M

Notes
: [ASSUMPTION] runtime_kv already exposed via registries.
---
Task Title
: Turn Scheduler Core Loop

Why / Outcome
: Enforce deterministic tick ordering for players and monsters; integrate with command dispatcher.

Changes
: `src/mutants/app/__init__.py`, `src/mutants/engine/session.py`, `src/mutants/services/turn_scheduler.py` [new]

APIs & Data
: `TurnScheduler.tick(player_action: Callable[..., Any]) -> None`; scheduler coordinates `player_action` then `monster_turns`.

Acceptance Criteria
: Every command (valid/invalid) advances scheduler; logs tick id; integrates RNG seed.

Tests
: Integration test simulating three commands and verifying tick counter increments.

Dependencies
: Runtime RNG Seed Registry

Complexity
: L

Notes
: [PROPOSED] scheduler stores pending monster queue in memory with persistence stub.
---
Task Title
: Invalid Command Turn Accounting

Why / Outcome
: Ensure gibberish commands still consume a turn per requirement.

Changes
: `src/mutants/commands/_helpers.py`, `src/mutants/app/__init__.py`

APIs & Data
: Hook dispatcher fallback to call `TurnScheduler.advance_invalid()`.

Acceptance Criteria
: Issue unknown command -> scheduler tick increments, monsters can act next.

Tests
: Integration test sending invalid command verifying tick log and monster action invoked.

Dependencies
: Turn Scheduler Core Loop

Complexity
: S

Notes
: —
---
Task Title
: Login Entry Target Roll Guard

Why / Outcome
: Implement special-case behaviour when entering a tile already hosting monsters after class switch.

Changes
: `src/mutants/services/player_login.py` [new or existing], `src/mutants/services/monster_actions.py`

APIs & Data
: Provide `monster_actions.roll_entry_target(monster, player_state, rng)` returning taunt/no-taunt result without attack.

Acceptance Criteria
: On login to occupied tile, monsters perform target roll only, no damage/log lines, scheduler records pass-through.

Tests
: Scenario test using fake monster verifying only target set, no attack event.

Dependencies
: Turn Scheduler Core Loop, Wake Trigger Service

Complexity
: M

Notes
: [ASSUMPTION] entry hook invoked from class menu flow.
---
Task Title
: Mitigation Curve Implementation

Why / Outcome
: Apply 3.15 damage reduction per +10 AC with rounding as per notes.

Changes
: `src/mutants/services/damage_engine.py`, `src/mutants/services/combat_calc.py`

APIs & Data
: New helper `apply_ac_mitigation(raw_damage: int, ac: int) -> int` using formula `raw - round((ac/10)*3.15)`.

Acceptance Criteria
: Damage floors respect MIN_INNATE/BOLT; tests verify sample AC vs damage cases.

Tests
: Unit tests covering AC 0/10/25/47 scenarios ensuring rounding rules.

Dependencies
: Baseline Combat Config Module

Complexity
: M

Notes
: [ASSUMPTION] apply curve before strike min-damage clamp.
---
Task Title
: Status Effect Scaffold

Why / Outcome
: Prepare data structures for future statuses (poison, stun) even if unused now.

Changes
: `src/mutants/services/status_manager.py` [new], `src/mutants/services/player_state.py`, `src/mutants/services/monsters_state.py`

APIs & Data
: `StatusManager.apply(entity_id, status_id, duration)` storing in timers_json.

Acceptance Criteria
: Entities can receive status entries; manager integrates with scheduler tick decrement.

Tests
: Unit tests for apply/expire flows.

Dependencies
: Schema Migration for Target & AI State

Complexity
: M

Notes
: [PLACEHOLDER] real effects implemented later.
---
Task Title
: Player Heal Command Implementation

Why / Outcome
: Add `heal` command obeying level+5 HP and class-specific ion cost.

Changes
: `src/mutants/commands/heal.py` [new], `src/mutants/commands/register_all.py`, `src/mutants/services/player_state.py`

APIs & Data
: `heal_cmd(arg, ctx)` consumes `ions` and restores HP.

Acceptance Criteria
: Heal recovers correct HP, charges per class (Warrior/Priest 750*level, Mage 1200*level, Wizard 1000*level, Thief 200*level). Fails if insufficient ions. Feedback bus prints consumed amount.

Tests
: Unit tests per class verifying HP/ions adjustments.

Dependencies
: Turn Scheduler Core Loop

Complexity
: M

Notes
: —
---
Task Title
: Heal Cost Validation & Logging

Why / Outcome
: Ensure heal command uses consistent messaging and logs for balancing.

Changes
: `src/mutants/debug/turnlog.py`, `src/mutants/ui/renderer.py`

APIs & Data
: Emit `COMBAT/HEAL` with fields `actor`, `hp_restored`, `ions_spent`.

Acceptance Criteria
: Log entry produced on heal; UI shows “You restore X hit points (Y ions).”

Tests
: Turnlog test verifying payload; renderer snapshot test for message.

Dependencies
: Player Heal Command Implementation

Complexity
: S

Notes
: —
---
Task Title
: Auto-Strike After Wield Ready

Why / Outcome
: Guarantee immediate strike when player targets then wields per note C16.

Changes
: `src/mutants/commands/wield.py`, `src/mutants/commands/strike.py`

APIs & Data
: Hook wield command to detect active ready target and call strike as part of same turn.

Acceptance Criteria
: Wielding a weapon while a target is readied triggers strike damage log once per wield.

Tests
: Integration test covering target->wield flow hitting monster.

Dependencies
: Turn Scheduler Core Loop, Mitigation Curve Implementation

Complexity
: M

Notes
: —
---
Task Title
: Wake Trigger Service

Why / Outcome
: Implement LOOK/ENTRY wake rolls with optional per-monster overrides.

Changes
: `src/mutants/services/monster_ai/wake.py` [new], `src/mutants/services/monster_actions.py`

APIs & Data
: `should_wake(monster, event, rng, config) -> bool` with default thresholds 15/10, plus override fields (`wake_on_look`, `wake_on_entry`).

Acceptance Criteria
: LOOK/ENTRY events call service; failing both prevents cascade.

Tests
: Unit tests verifying thresholds and overrides.

Dependencies
: Runtime RNG Seed Registry, Baseline Combat Config Module

Complexity
: M

Notes
: —
---
Task Title
: Cascade Evaluator Implementation

Why / Outcome
: Realize priority gates FLEE→HEAL→CONVERT→CAST→ATTACK→PICKUP→EMOTE→IDLE per spec.

Changes
: `src/mutants/services/monster_ai/cascade.py` [new], `src/mutants/services/monster_actions.py`

APIs & Data
: `evaluate_cascade(monster, context) -> ActionResult` with gate definitions referencing config thresholds.

Acceptance Criteria
: First satisfied gate executes, logs reason, cracked bias adjustments applied.

Tests
: Unit tests simulating gate ordering and cracked bias.

Dependencies
: Wake Trigger Service, Mitigation Curve Implementation

Complexity
: L

Notes
: —
---
Task Title
: Cracked Bias Adjustments

Why / Outcome
: Modify gate weights when wielded weapon cracked as per spec.

Changes
: `src/mutants/services/monster_ai/cascade.py`, `monster_actions.py`

APIs & Data
: When `wielded.cracked`, halve attack weight, +10 pickup pct, +5 flee pct.

Acceptance Criteria
: Tests show bias applied only while cracked weapon equipped.

Tests
: Unit test toggling cracked flag verifying weight changes.

Dependencies
: Cascade Evaluator Implementation, Wear Application Harmonization

Complexity
: S

Notes
: —
---
Task Title
: Attack Weight Resolver

Why / Outcome
: Choose melee/ranged/innate based on inventory mix and `prefers_ranged` hint.

Changes
: `src/mutants/services/monster_ai/attack_selection.py` [new], `monster_actions.py`

APIs & Data
: `select_attack(monster, context) -> AttackPlan` returns source + item iid.

Acceptance Criteria
: Weight table matches spec (70/20/10 etc.); cracked penalty halves relevant weight.

Tests
: Unit tests for combos (melee-only, ranged-only, with prefers_ranged true/false).

Dependencies
: Cracked Bias Adjustments

Complexity
: M

Notes
: —
---
Task Title
: Convert Eligibility Enforcement

Why / Outcome
: Restrict monster conversions to pickup-origin items only.

Changes
: `src/mutants/services/monster_actions.py`, `monster_ai/cascade.py`

APIs & Data
: `_ai_state['picked_up']` list check before invoking convert; mark conversions in summary.

Acceptance Criteria
: Monster never converts native gear; tests verify.

Tests
: Unit test simulating native vs picked_up item.

Dependencies
: Cascade Evaluator Implementation

Complexity
: S

Notes
: —
---
Task Title
: Monster Heal Gate Integration

Why / Outcome
: Implement heal gate using Thief economics (conflict resolution) and visual line.

Changes
: `src/mutants/services/monster_ai/heal.py` [new], `monster_actions.py`

APIs & Data
: Heal consumes `level * 200` ions, restores `level + 5` HP, emits bus line `{monster}'s body is glowing!`.

Acceptance Criteria
: Heal gate fires under HP%<80 and enough ions; ion ledger updates.

Tests
: Unit tests verifying HP and ion adjustments.

Dependencies
: Convert Eligibility Enforcement, Baseline Combat Config Module

Complexity
: M

Notes
: [PROPOSED] Heal amount capped at missing HP.
---
Task Title
: Monster Ion Ledger Sync

Why / Outcome
: Track ion/riblet balances for monsters (loot transfer on kills, heals spend ions).

Changes
: `src/mutants/services/monsters_state.py`, `monster_actions.py`

APIs & Data
: Extend monster payload to include `ions` and `riblets` fields persisted in `ai_state_json`.

Acceptance Criteria
: Killing player updates monster ions/riblets; heal gate consumes from ledger.

Tests
: Unit tests verifying persistence and spending.

Dependencies
: Schema Migration for Target & AI State, Monster Heal Gate Integration

Complexity
: M

Notes
: —
---
Task Title
: Casting Gate Logic

Why / Outcome
: Implement CAST gate with success/failure handling per spec (75% success, costs 10 ions default, half on fail) and low-ion adjustments.

Changes
: `src/mutants/services/monster_ai/casting.py` [new], `monster_actions.py`

APIs & Data
: `try_cast(monster, context) -> CastResult` returning success flag and effect placeholder.

Acceptance Criteria
: Low-ion (<LOW_ION%) reduces CAST/HEAL pct by 40% and boosts CONVERT by +10.

Tests
: Unit tests covering success, failure, low-ion adjustments.

Dependencies
: Monster Ion Ledger Sync, Baseline Combat Config Module

Complexity
: M

Notes
: [PLACEHOLDER] actual spell effects stubbed with logging.
---
Task Title
: Wear Application Harmonization

Why / Outcome
: Ensure monsters use deterministic wear amount 5 and interact with `items_wear` service uniformly.

Changes
: `src/mutants/services/monster_actions.py`, `src/mutants/services/items_wear.py`

APIs & Data
: Guarantee `wear_from_event` invoked with consistent payload; log cracks via bus.

Acceptance Criteria
: Wear events for both player and monster hits produce identical cracks after 20 hits if degradable.

Tests
: Unit tests verifying wear counters for sample weapon.

Dependencies
: Mitigation Curve Implementation

Complexity
: S

Notes
: —
---
Task Title
: Broken Gear Drop Scheduler

Why / Outcome
: Implement immediate armour drop and weapon drop scheduling (80% chance per turn) for cracked gear.

Changes
: `src/mutants/services/monster_ai/inventory.py`, `monster_actions.py`

APIs & Data
: Track `ai_state['pending_drop']`; drop occurs before cascade evaluation when triggered.

Acceptance Criteria
: Armour removed same turn; weapon drop triggered within two turns on average; broken gear left on ground.

Tests
: Unit tests verifying drop scheduling state machine.

Dependencies
: Wear Application Harmonization, Cascade Evaluator Implementation

Complexity
: M

Notes
: —
---
Task Title
: Pickup Filtering & Scoring Update

Why / Outcome
: Enforce broken-item filter and improved scoring per spec.

Changes
: `src/mutants/services/monster_actions.py`

APIs & Data
: `_score_pickup_candidate` returns 0 for broken placeholders; filters on pickup gate.

Acceptance Criteria
: Monsters ignore broken items; prefer higher base damage/ion value items.

Tests
: Unit tests comparing candidate lists.

Dependencies
: Broken Gear Drop Scheduler

Complexity
: S

Notes
: —
---
Task Title
: Auto-Equip Upgrade Hook

Why / Outcome
: Swap to better weapons/armour immediately upon pickup.

Changes
: `src/mutants/services/monster_ai/inventory.py`, `monsters_state.py`

APIs & Data
: Evaluate derived damage/AC; update `wielded`/`armour_slot` fields; adjust bag.

Acceptance Criteria
: When higher damage weapon found, monster wields it same tick (respecting `prefers_ranged`).

Tests
: Unit tests verifying upgrade logic for melee vs ranged.

Dependencies
: Pickup Filtering & Scoring Update

Complexity
: M

Notes
: —
---
Task Title
: Flee Decision Logic

Why / Outcome
: Apply HP%, cracked weapon, and level difference modifiers to FLEE gate.

Changes
: `src/mutants/services/monster_ai/cascade.py`

APIs & Data
: Evaluate `hp.current/hp.max`, adjust percentages (+5/-5) based on level delta.

Acceptance Criteria
: FLEE gate probability matches spec; additional cracked panic check when out-leveled by ≥5.

Tests
: Unit tests verifying computed flee pct in sample scenarios.

Dependencies
: Cascade Evaluator Implementation

Complexity
: S

Notes
: —
---
Task Title
: Pursuit Behaviour Implementation

Why / Outcome
: Implement 70% chase roll with modifiers and world path fallback.

Changes
: `src/mutants/services/monster_ai/pursuit.py` [new], `monster_actions.py`, `src/mutants/world/years.py`

APIs & Data
: `attempt_pursuit(monster, target_pos, rng) -> bool`; apply modifiers for loot, low ions, low HP, cracked gear.

Acceptance Criteria
: Successful pursuit moves monster via world path; failure logs reason and continues cascade.

Tests
: Unit tests mocking pathing; integration test verifying chase after player flees.

Dependencies
: Flee Decision Logic, Auto-Equip Upgrade Hook

Complexity
: M

Notes
: —
---
Task Title
: Emote Free Action Scheduler

Why / Outcome
: Allow yelling/emotes without consuming turn per C15.

Changes
: `src/mutants/services/monster_ai/emote.py` [new], `TurnScheduler`

APIs & Data
: After cascade resolves IDLE or EMOTE gate, schedule separate “free emote” roll that does not advance turn counter.

Acceptance Criteria
: Logs emote lines independently; tick counter unchanged.

Tests
: Scheduler test verifying emote event does not increment tick.

Dependencies
: Emote Library Wiring, Turn Scheduler Core Loop

Complexity
: M

Notes
: —
---
Task Title
: Post-Kill Bonus Action Hook

Why / Outcome
: Grant extra cascade evaluation after monster kills an entity with 25% pickup bias.

Changes
: `src/mutants/services/monster_ai/cascade.py`, `TurnScheduler`

APIs & Data
: On kill event, scheduler enqueues `bonus_action` flag causing next cascade to skip wake and optionally force pickup.

Acceptance Criteria
: Bonus action executes immediately; 25% of cases force pickup gate when loot available.

Tests
: Unit test verifying forced pickup probability and single extra evaluation.

Dependencies
: Cascade Evaluator Implementation, Monster Loot Ordering Routine

Complexity
: M

Notes
: —
---
Task Title
: Monster Loot Ordering Routine

Why / Outcome
: Enforce drop order (carried items → skull → worn armour) and handle ground overflow deletion.

Changes
: `src/mutants/services/combat_loot.py`, `src/mutants/services/monster_actions.py`

APIs & Data
: Extend `drop_monster_loot` to accept sorted lists; create `drop_summary` describing vaporized items.

Acceptance Criteria
: Drops follow order; ground full leads to logged deletion; tests verify order.

Tests
: Unit tests with mocked ground capacity.

Dependencies
: Turn Scheduler Core Loop

Complexity
: M

Notes
: —
---
Task Title
: Ground Capacity Check

Why / Outcome
: Ensure overflow items are removed when room inventory full.

Changes
: `src/mutants/services/combat_loot.py`, `src/mutants/registries/items_instances.py`

APIs & Data
: `is_ground_full(year,x,y) -> bool`; drop routine deletes extras with log “Ground is full; {item} dissipates.”

Acceptance Criteria
: When capacity reached, items not spawned and log emitted.

Tests
: Unit test verifying overflow behavior.

Dependencies
: Monster Loot Ordering Routine

Complexity
: S

Notes
: —
---
Task Title
: Player Death Placeholder Handler

Why / Outcome
: Implement non-punishing respawn at (2000,0,0) with loot transfer to killer.

Changes
: `src/mutants/services/player_death.py` [new], `player_state.py`, `TurnScheduler`

APIs & Data
: `handle_player_death(player_id, killer_monster)` resets HP, pos, target, inventory cleared, ions/riblets transferred.

Acceptance Criteria
: Player respawns with base HP and 30k ions (per existing start), monsters receive transferred currencies.

Tests
: Integration test verifying respawn state and monster ledger update.

Dependencies
: Monster Ion Ledger Sync, Turn Scheduler Core Loop

Complexity
: M

Notes
: [ASSUMPTION] Player retains experience.
---
Task Title
: Target Reset Hooks

Why / Outcome
: Clear targets on player death, exit, or monster death.

Changes
: `src/mutants/services/player_state.py`, `src/mutants/commands/close.py`, `monster_actions.py`

APIs & Data
: Utility `clear_target(reason)` invoked on exit/death; ensures monster target cleared.

Acceptance Criteria
: After player exit, both sides no longer reference target IDs.

Tests
: Unit tests verifying target removal events.

Dependencies
: Player Death Placeholder Handler

Complexity
: S

Notes
: —
---
Task Title
: Cross-Year Target Wake Hook

Why / Outcome
: Ensure monsters track targets across years and act immediately when player re-enters.

Changes
: `src/mutants/services/monster_ai/tracking.py` [new], `monster_actions.py`

APIs & Data
: Maintain `ai_state['target_positions']`; on player entering year with targeting monster, scheduler schedules immediate action.

Acceptance Criteria
: Player re-entering year triggers monster action within same tick.

Tests
: Integration test with travel command verifying immediate response.

Dependencies
: Target Persistence Schema Upgrade, Wake Trigger Service

Complexity
: M

Notes
: —
---
Task Title
: Monster Taunt & Ready Messaging Hook

Why / Outcome
: Emit taunt line when monster targets player, with 5% chance to append “{monster} is getting ready to combat you!”.

Changes
: `src/mutants/services/monster_ai/taunt.py` [new], `monster_actions.py`, `ui/renderer.py`

APIs & Data
: `emit_taunt(monster, bus, rng)`; ensures taunt only on targeting.

Acceptance Criteria
: Taunt occurs exactly once per targeting event; 5% follow-up message logged.

Tests
: Unit test verifying probability using seeded RNG.

Dependencies
: Wake Trigger Service, Feedback Templates Audit

Complexity
: S

Notes
: —
---
Task Title
: Feedback Templates Audit

Why / Outcome
: Align combat feedback strings with spec tokens.

Changes
: `src/mutants/ui/renderer.py`, `ui/textutils.py`, `debug/turnlog.py`

APIs & Data
: Centralize templates: melee `{monster} has hit you with his {weapon}!`, ranged variants, convert/heal/drop lines.

Acceptance Criteria
: All combat events use canonical templates with placeholders.

Tests
: Renderer snapshot tests verifying string outputs.

Dependencies
: Monster Taunt & Ready Messaging Hook, Monster Heal Gate Integration

Complexity
: M

Notes
: —
---
Task Title
: Emote Library Wiring

Why / Outcome
: Integrate 20-line emote list and ensure EMOTE gate picks random line.

Changes
: `src/mutants/services/monster_ai/emote.py`, `ui/renderer.py`

APIs & Data
: Provide `EMOTE_LINES` constant; emitter selects deterministic via RNG.

Acceptance Criteria
: Emote gate outputs one of 20 lines; duplicates allowed.

Tests
: Unit test verifying line coverage via seeded RNG.

Dependencies
: Feedback Templates Audit

Complexity
: S

Notes
: —
---
Task Title
: Shadow Renderer Integration

Why / Outcome
: Display “You see shadows to the {dir}” when monsters adjacent; update on pursuit.

Changes
: `src/mutants/ui/renderer.py`, `src/mutants/world/vision.py` [new]

APIs & Data
: `list_adjacent_monsters(player_pos) -> list[Direction]`; renderer formats lines with cardinal/diagonal names.

Acceptance Criteria
: Adjacent monsters produce shadow line; clearing when monster leaves.

Tests
: Unit tests verifying direction naming and toggling.

Dependencies
: Turn Scheduler Core Loop

Complexity
: M

Notes
: —
---
Task Title
: Audio Cue Propagation Service

Why / Outcome
: Handle yelling/footstep sounds up to 4 tiles, with “far” for >1 tile.

Changes
: `src/mutants/services/audio_cues.py` [new], `ui/renderer.py`

APIs & Data
: `emit_sound(monster_pos, player_pos, kind)` calculates distance/direction; logs “You hear yelling to the southwest.” or “… far to the west.”

Acceptance Criteria
: Distance >1 tile adds “far”; >4 tiles no cue. Footsteps triggered on pursuit/move.

Tests
: Unit tests for distance/direction formatting.

Dependencies
: Pursuit Behaviour Implementation, Turn Scheduler Core Loop

Complexity
: M

Notes
: —
---
Task Title
: Species Hint Loader

Why / Outcome
: Apply species-specific AI nudges from catalog (prefers_ranged, brood tags, undead etc.).

Changes
: `src/mutants/services/monster_entities.py`, `monster_ai/cascade.py`

APIs & Data
: Load `prefers_ranged` and custom modifiers from catalog metadata or overrides.

Acceptance Criteria
: Nudges reflected in cascade percentages for sample catalog entries (junkyard_scrapper, rad_swarm_matron, titan_of_chrome).

Tests
: Unit tests verifying overrides applied when monster_id matches.

Dependencies
: Baseline Combat Config Module

Complexity
: S

Notes
: —
---
Task Title
: Monster Config Overrides Loader

Why / Outcome
: Allow runtime hints (prefers_ranged, wake overrides) without schema changes.

Changes
: `src/mutants/services/monster_entities.py`, `monsters_catalog.py`

APIs & Data
: Extend catalog loader to read optional `ai_overrides` dict.

Acceptance Criteria
: Overrides accessible on monster instances; default to None when missing.

Tests
: Unit test verifying overrides parsed from catalog JSON.

Dependencies
: Species Hint Loader

Complexity
: S

Notes
: —
---
Task Title
: Player Name Default Wiring

Why / Outcome
: Default player display name to “Vindeiatrix” when names absent.

Changes
: `src/mutants/services/player_state.py`, `ui/renderer.py`

APIs & Data
: Provide `get_player_display_name()` returning stored name or fallback constant.

Acceptance Criteria
: UI consistently shows Vindeiatrix for nameless player entries.

Tests
: Unit test verifying fallback behaviour.

Dependencies
: Feedback Templates Audit

Complexity
: S

Notes
: —
---
Task Title
: Monster Heal Visual Feedback

Why / Outcome
: Ensure heal logs display to player (“{monster}'s body is glowing!”).

Changes
: `ui/renderer.py`, `monster_ai/heal.py`

APIs & Data
: Use feedback bus to push `COMBAT/HEAL_MONSTER` topic with template.

Acceptance Criteria
: Heal gate triggers renderer message once per heal action.

Tests
: Renderer snapshot test verifying string.

Dependencies
: Monster Heal Gate Integration, Feedback Templates Audit

Complexity
: S

Notes
: —
---
Task Title
: Monster Kill Reward Transfer

Why / Outcome
: When monster kills player, transfer player ions/riblets to monster ledger and persist.

Changes
: `monster_actions.py`, `player_death.py`

APIs & Data
: On kill event, call `monster_ledger.deposit(ions, riblets)`.

Acceptance Criteria
: Player balances zeroed; monster ledger increases accordingly.

Tests
: Integration test verifying transfer.

Dependencies
: Monster Ion Ledger Sync, Player Death Placeholder Handler

Complexity
: S

Notes
: —
---
Task Title
: Casting Feedback & Spell Placeholder

Why / Outcome
: Emit cast attempt/success/failure messages per template and stub spell effects.

Changes
: `monster_ai/casting.py`, `ui/renderer.py`

APIs & Data
: On success, push `COMBAT/SPELL` with `{monster}` and `{spell}` tokens; on failure, optional fizzled message [PROPOSED].

Acceptance Criteria
: Logs match spec strings; failure halves cost.

Tests
: Unit test verifying messages.

Dependencies
: Casting Gate Logic, Feedback Templates Audit

Complexity
: S

Notes
: [PROPOSED] Failure message “{monster}'s spell fizzles out.”
---
Task Title
: AI Checklist Verification Tests

Why / Outcome
: Ensure every checklist item from spec validated via automated tests.

Changes
: `tests/ai/test_monster_ai_checklist.py`

APIs & Data
: Scenario harness running seeded combat simulation verifying gates and outputs.

Acceptance Criteria
: Tests cover wake, cascade order, heal, convert, pickup filter, pursuit, post-kill action.

Tests
: The test file itself (golden assertions).

Dependencies
: All AI implementation tasks (cascade, heal, pursuit, etc.)

Complexity
: L

Notes
: —
---
Task Title
: Golden Combat Log Generation

Why / Outcome
: Generate canonical logs for regression comparison.

Changes
: `tests/golden/test_combat_logs.py`, `tools/generate_combat_log.py`

APIs & Data
: Use seedable RNG to produce log file; compare to stored golden text.

Acceptance Criteria
: Golden test passes when logs unchanged; diff highlights regressions.

Tests
: Pytest golden test.

Dependencies
: Runtime RNG Seed Registry, Feedback Templates Audit

Complexity
: M

Notes
: —
---
Task Title
: Balance Knob Documentation

Why / Outcome
: Document config knobs and how to tune gates/heal costs.

Changes
: `docs/combat_tuning.md`, `docs/index.md`

APIs & Data
: Markdown documentation referencing config file fields.

Acceptance Criteria
: Docs describe each knob, default value, related requirement ID.

Tests
: Documentation lint (if available) or manual review.

Dependencies
: Baseline Combat Config Module

Complexity
: S

Notes
: [PROPOSED] Include table of knobs vs effects.
---
Task Title
: Monster Travel Footstep Logging

Why / Outcome
: Emit footsteps audio cue when monster moves due to pursuit.

Changes
: `monster_ai/pursuit.py`, `audio_cues.py`

APIs & Data
: On movement success, call `emit_sound(..., kind="footsteps")`.

Acceptance Criteria
: Player hears footsteps when monster moves within 4 tiles.

Tests
: Integration test verifying cue output.

Dependencies
: Pursuit Behaviour Implementation, Audio Cue Propagation Service

Complexity
: S

Notes
: —
---
Task Title
: Heal Command Ion Cost Config Knob

Why / Outcome
: Allow overriding heal ion cost multipliers via config for balancing.

Changes
: `combat_config.py`, `commands/heal.py`

APIs & Data
: Config keys `heal_cost_multiplier.<class>` default to specified values.

Acceptance Criteria
: Changing config updates runtime cost without code change.

Tests
: Unit test overriding config verifying new cost applied.

Dependencies
: Player Heal Command Implementation, Baseline Combat Config Module

Complexity
: S

Notes
: —
---
Task Title
: Monster Spawner Death Hooks

Why / Outcome
: Ensure spawner notices monster death and schedules respawn stubs.

Changes
: `monster_spawner.py`, `monster_actions.py`

APIs & Data
: On kill, mark year for future spawn; placeholder respawn logic.

Acceptance Criteria
: Death triggers spawner dirty flag; respawn stub logged.

Tests
: Unit test verifying spawner state update.

Dependencies
: Monster Loot Ordering Routine

Complexity
: S

Notes
: [PLACEHOLDER] Actual respawn timing to be tuned later.
---
Task Title
: Monster Bonus Pickup Bias Config

Why / Outcome
: Make 25% forced pickup probability configurable.

Changes
: `combat_config.py`, `monster_ai/cascade.py`

APIs & Data
: Config key `post_kill_force_pickup_pct` default 25.

Acceptance Criteria
: Changing config updates behaviour.

Tests
: Unit test verifying new config value applied.

Dependencies
: Post-Kill Bonus Action Hook, Baseline Combat Config Module

Complexity
: S

Notes
: —

## Formulas & Contracts
```text
// Initiative & Tick Ordering [PROPOSED]
Each player command -> advance global tick.
Monster initiative score = rng(0, 99) + (monster.dex // 5).
Tie-breaker: lower instance_id lexicographically.
```

```text
// To-Hit & Damage [PROPOSED]
attack_power = base_power + 4*enchant + strength_bonus.
mitigated_damage = attack_power - round((total_ac / 10) * 3.15).
minimum_damage = { bolt: 6, innate: max(6, innate_base), melee: max(1, mitigated_damage) }.
crit_trigger = rng(0,99) < CRIT_PCT (default 5) => x1.5 damage (rounded).
fumble_trigger = rng(0,99) < FUMBLE_PCT (default 3) => damage = 0, apply self stun 1 tick.
```

```text
// Status Durations [PROPOSED]
BLEED: 3 ticks, stacking adds +1 tick up to 6.
STUN: 1 tick, non-stacking (refresh duration).
```

```text
// Heal Economics
player_heal_hp = level + 5.
player_heal_cost = class_multiplier * level  // multipliers per class; Thief=200, Warrior/Priest=750, Mage=1200, Wizard=1000.
monster_heal_hp = level + 5 (cap at missing HP).
monster_heal_cost = 200 * level (per conflict resolution).
```

```text
// Initiative Wake & Pursuit
Wake on LOOK: rng(0,99) < WAKE_ON_LOOK (default 15, overrides ±10).
Wake on ENTRY: rng(0,99) < WAKE_ON_ENTRY (default 10).
Pursuit chance = 70 + modifiers (-20 loot, -15 low ions, -20 low HP, -25 cracked).
```

```text
// Status Persistence JSON Layout [PROPOSED]
{
  "timers": {
    "stun": {"remaining": 1},
    "bleed": {"remaining": 3, "stacks": 2}
  }
}
```

## Logging & Messaging
- **Combat attacks:** `{monster} has hit you with his {weapon}!`, `{monster} shoots a bolt from his {weapon}!`, `{monster} fires his {weapon} at you!`, innate line from catalog.
- **Taunt:** `{monster} says: {taunt}` (existing line) plus optional `{monster} is getting ready to combat you!` (5%).
- **Heal:** Player: `You restore {hp} hit points (cost {ions} ions).` Monster: `{monster}'s body is glowing!`
- **Convert:** `You see a blinding white flash illuminate from {monster}'s body!`
- **Pickup/Drop:** `{monster} picked up {item}.`, `{monster} dropped {item}.`
- **Weapon crack:** `{monster}'s {weapon} cracks!`
- **Arrive/Leave:** `{monster} has just arrived from {dir}.`, `{monster} has just left {dir}.`
- **Audio cues:** `You hear yelling to the {dir}.`, `You hear footsteps far to the {dir}.`
- **Death:** Player kill: `You slay {monster}!` followed by `{monster} crumbles to dust.` Monster kill: `{monster} has slain you!` + respawn messaging.
- **Emotes:** 20-line library from spec; select using RNG.

## Risk & Open Questions
1. **Heal cost conflict:** Resolved via [PROPOSED] config knob, but requires confirmation that designer prefers Thief economics for monsters.
2. **Ground capacity limit:** Need explicit capacity number—[ASSUMPTION] reuse existing world inventory cap (confirm exact value).
3. **Turn scheduler persistence:** Deciding whether to persist initiative queue between process restarts; current plan treats queue as in-memory [PROPOSED].
4. **Crit/fumble system:** Not defined in source docs; proposed rates may require product approval.
5. **Player death inventory handling:** Notes specify non-punishing respawn, but what happens to equipped items? [OPEN] assume items drop or are deleted? Proposed to drop carried items per death routine.
6. **Audio direction naming:** Need confirmation on exact wording (“southwest” vs “to the southwest”). [ASSUMPTION] use `to the southwest` phrasing.
7. **World path blocking:** Pursuit fallback may require more sophisticated pathfinding if exits blocked; to revisit after baseline.

## Getting Started
1. **Baseline Combat Config Module** – unlocks centralized knobs for downstream tasks.
2. **Schema Migration for Target & AI State** – persist new fields needed by AI and scheduler.
3. **Turn Scheduler Core Loop** – integrate command ticks before implementing combat/AI behaviours.

