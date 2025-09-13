# Mutants — Dense Architecture Notes (for AI/maintainers)

## Runtime loop (REPL)
- Pattern: **Read → Eval → Print → Loop**.
- File: `repl/loop.py` (metronome). It:
  1) builds the **app context** (`app/context.py`);
  2) creates a **Dispatch** router (`repl/dispatch.py`);
  3) calls `commands.register_all.register_all(dispatch, ctx)` to auto-register all commands;
  4) prints a banner; initial `render_frame(ctx, policy=RenderPolicy.ROOM)`;
  5) for each input line: split `token arg`; `dispatch.call(token, arg)`; re-render **only** when the command returns `RenderPolicy.ROOM` (movement and `look`).

## App context (single source of wiring)
- File: `app/context.py`.
- Holds: `player_state`, `world_loader`, optional `items`/`monsters` registries, `headers`,
  `feedback_bus`, `logsink` (subscribed to bus), `theme` (JSON), `renderer` callable.
- Helpers:
  - `build_context()` returns the dict above.
  - `build_room_vm(ctx)` constructs UI data for current tile (no I/O in renderer).
  - `render_frame(ctx, policy)` builds RoomVM, drains bus, invokes renderer with theme palette/width, prints lines + prompt (when ``policy`` permits).

## Command routing
- `repl/dispatch.py`:
  - `.register("north", fn)`, `.alias("n","north")`, `.call(token,arg)`.
  - Unknown commands push `SYSTEM/WARN` to **Feedback Bus**.
  - `.list_commands()` supports help generation.

## Command modules (auto-discovered)
- Each `mutants.commands.<name>` with a top-level `register(dispatch, ctx)` is loaded and registered by `commands/register_all.py`.
- Example (`commands/move.py`):
  - registers `north/n`, `south/s`, `east/e`, `west/w`, `look`;
  - inspects world edges via `registries/world.py`;
  - on block: `bus.push("MOVE/BLOCKED", "...")`; on success: optionally `bus.push("MOVE/OK","...")`;
  - **does not print**; REPL repaints only when the command returns ``RenderPolicy.ROOM``.

## UI stack (pure, testable)
- **ViewModel**: `ui/viewmodels.py` — RoomVM shape consumed by renderer.
- **Formatters**: `ui/formatters.py` — text → tokenized segments (no ANSI).
- **Styles**: `ui/styles.py` — token names + resolver (`resolve_segments`, `tagged_string`).
- **Color Groups**: every formatted text fragment can declare a `group` (dotted string). `styles.resolve_color_for_group(group)` looks up `state/ui/colors.json` with fallback: exact → `prefix.*` → `defaults` → `"white"`. Existing color-by-name calls still work via `styles.colorize_text`.
- **Themes**: `ui/themes.py` — loads JSON `state/ui/themes/<name>.json` → `Theme { palette, width }` (no code changes needed to tweak colors).
- **Wrap**: `ui/wrap.py` — ANSI-aware 80-col wrapping (only list sections wrap).
- **Renderer**: `ui/renderer.py` — builds ordered blocks then joins them with a single `***` **between** blocks only (no leading/trailing or double separators).  Blocks: core (room/compass/directions), ground, monsters, cues. Renderer uses `Theme.palette` + `Theme.width`.

#### Wrapping implementation
* `ui/wrap.py` exposes `wrap(text, width=80)` using `textwrap.TextWrapper` with `break_on_hyphens=False` and `break_long_words=False` so names like `Ion-Decay` never split.
* Inventory and ground lists call this helper before emitting lines to ensure consistent 80-col behavior.

### Data Flow (UI)
VM → Formatters (build strings + **group**) → Styles (resolve color by group) → Renderer (layout/output)

### UI Contract: Direction List Is Open-Only
* **Invariant:** The direction list must show only *open/continuous* exits (“area continues.”) and must not show blocked entries (terrain/boundary/gates).
* **Implementation (minimal):** The renderer iterates `vm["dirs_open"]` when present; if not present, it filters `vm["dirs"]` to open-only (`edge.base == 0`) before rendering.
* **Guardrail:** With `MUTANTS_DEV=1`, the renderer asserts if a non-open edge appears in `dirs_open`; otherwise it logs a warning and drops it. This prevents downstream refactors (formatting/color) from resurrecting blocked rows.
* **Separation of concerns:** Movement failures should surface via feedback lines (e.g., “You’re blocked!”) rather than as direction rows.

### UI Contract: Ground Block
* **Trigger:** VM sets `has_ground=True` and provides non-empty `ground_item_ids: List[str]`.
* **Rendering:** Renderer prints one fixed header `On the ground lies:` followed by a comma-separated list of items, wrapped to **80 columns**, with a trailing period. See `uicontract.py` constants: `GROUND_HEADER`, `UI_WRAP_WIDTH`.
* **Separators:** Exactly one `***` before and one `***` after the ground block. The post-direction separator is reused if already present.
* **Guardrail:** If `has_ground=True` but `ground_item_ids` is empty, the renderer asserts under `MUTANTS_DEV=1` or logs-and-drops in normal runs.

### UI Contract: Monsters & Cues
* **Monsters:** If `vm["monsters_here"]` is non-empty, render:
  - 1 name → `"<Name> is here."`
  - 2+ names → `"<A>, <B>, and <C> are here with you."` (serial-comma style)
  Precede with a single `***` and append a single `***` after.
* **Cues:** If `vm["cues_lines"]` has entries, print each string as a line; insert a single `***` **between** cue lines (not after the last). The UI does not synthesize wording—strings come from the VM.
* **Placement:** This block appears **after** the Ground block and adheres to the single-separator rule to avoid doubles, matching the originals. 

### Locked Literals and Descriptors
* Canonical literals and descriptors live in `src/mutants/ui/uicontract.py`:
  - `COMPASS_PREFIX = "Compass: "`
  - `DIR_LINE_FMT = "{:<5} - {}"`
  - `SEPARATOR_LINE = "***"`
  - Direction descriptors (closed set): `area continues.`, `wall of ice.`, `ion force field.`, `open gate.`, `closed gate.`
* The formatter normalizes open edges to `area continues.`; any future non-open wording must come from the same closed set.

## Feedback and logs (diagnostics)
- `ui/feedback.py` — **Feedback Bus** (structured events):
  - `.push(kind, text, **meta)`; `.drain()`; `.subscribe(listener)`.
  - Common kinds: `SYSTEM/OK|WARN|ERR`, `MOVE/OK|BLOCKED`, `GATE/OPEN|CLOSE|LOCKED|FAIL`, `LOOT/PICKUP|DROP`,
    `COMBAT/HIT|MISS|CRIT|TAUNT`, `SPELL/CAST|FAIL`, `DEBUG/...`.
- `ui/logsink.py` — **Ring buffer** + optional file append to `state/logs/game.log` (ISO timestamp, KIND, TEXT).
- Renderer styles feedback lines by **kind→token** mapping in the theme (e.g., `FEED_BLOCK` bold yellow).

## Passability & Dynamic Overlays
* **Resolver**: `engine/edge_resolver.py` is the canonical decision point (`resolve(world, dynamics, year,x,y,dir, actor)` → `EdgeDecision`), used by movement and future UI.
* **Two-sided composition**: the resolver reads **both** the current tile’s edge and the **neighbor tile’s opposite edge** (OOB/missing ⇒ boundary). A move is allowed **only if both sides permit** (or an open gate exists and neither side blocks).
* **Layers** (priority high→low): actor modifiers → dynamic overlays → gates/locks → base terrain. Base values may be **strings** or **numbers**; unknown/missing defaults to **boundary/blocked**.
* **Descriptors**: normalized to the closed set `{area continues., wall of ice., ion force field., open gate., closed gate.}`.
* **Dynamic registry**: `registries/dynamics.py` stores per-edge overlays in `state/world/dynamics.json` with TTL; spells/rods write here, resolver reads it.
* **UI guard**: Renderer validates each direction row through the resolver; in `MUTANTS_DEV=1` a blocked direction triggers an assertion; otherwise it is dropped with a warning log.

#### Verification Tooling
* **Edge sampler**: `logs verify edges [count]` samples random open tiles (current year) and checks resolver symmetry (**cur→dir** vs **neighbor→opp**). Mismatches are logged as `VERIFY/EDGE` warnings in `state/logs/game.log`, and a summary is shown in the feedback area.
* **Separator joiner**: `logs verify separators` runs synthetic scenarios to ensure the renderer never emits leading/trailing or consecutive `***` lines. Failures log `VERIFY/SEPARATORS` warnings.

## Tracing & WHY
* **Toggles**: `state/runtime/trace.json` stores `{"move":bool,"ui":bool}` toggled via `logs trace move on|off`.
* **Log format**: `MOVE/DECISION {"pos":"(xE : yN)","dir":"S","passable":false,"desc":"ion force field.","why":[["base","base:force"],["overlay","barrier:blastable"]]}`.
* **WHY command**: `why <dir>` prints a human-readable line for the current tile and direction using the same resolver.

## Registries (game data & live state)
- **World**: `registries/world.py` — YearWorld from `state/world/<year>.json`. Mirrored edge mutations (never modify `base=2` boundary). Atomic `save()`.
- **Items (base)**: `state/items/catalog.json`; loader `registries/items_catalog.py`.
- **Items (instances)**: `state/items/instances.json`; registry `registries/items_instances.py` (create_instance, enchant, wear, charges, save).
- **Monsters (base)**: `state/monsters/catalog.json`; loader `registries/monsters_catalog.py`; `exp_for(level, bonus=0)`.
- **Monsters (instances)**: `state/monsters/instances.json`; registry `registries/monsters_instances.py` (create_instance, targets, save).
- **Player state**: ensured by `bootstrap/lazyinit.py` (DEX→AC via `dex // 10`).

## Bootstrap & Discovery (no hard-coded years)

- `bootstrap/runtime.ensure_runtime()` runs at startup (from `app/context.py`):
  - ensures `state/` dirs
  - ensures `items/instances.json` and `monsters/instances.json`
  - ensures `state/ui/themes/bbs.json` and `mono.json` (JSON themes)
  - discovers world years from `state/world/*.json`
  - if none exist, **creates a minimal world** using `state/config.json` or defaults (`default_world_year=2000`, `default_world_size=30`)
- `registries/world.list_years()` reports available years; `load_nearest_year(y)` picks the closest.
- `bootstrap/lazyinit.ensure_player_state()` maps template `start_pos[0]` to the **nearest** existing year, so templates can always say `2000` without going stale.
- All modules read `player.pos[0]` at runtime; no code assumes `2000`.
 
## Daily Litter Spawn System
* **Inputs**: `state/items/catalog.json` (items with `"spawnable": true` and optional `"spawn": {"weight": int, "cap_per_year": int}`) and `state/items/spawn_rules.json` (`daily_target_per_year`, `max_ground_per_tile`).
* **Algorithm** (per day):
  1. Remove instances where `origin == "daily_litter"`.
  2. For each year, build a weighted pool of spawnable items that have not hit `cap_per_year` (counts include existing ground items).
  3. Iterate world tiles (`tile["pos"]`) at random; skip any tile already at capacity (default six items) and place until the daily target is met.
  4. Save instances, record today in `state/runtime/spawn_epoch.json`, log a summary line.
* **Determinism**: RNG seeded by `YYYY-MM-DD` keeps placement stable within the day.
* **Safety**: runs once at bootstrap; missing files/worlds merely log and skip.

#### Items Registry
* **Reader**: `registries/items_instances.py` provides `list_ids_at(year,x,y)` (IDs) and legacy `list_at(year,x,y)` (display names). Both recognize `{"pos":{...}}` and flat `{"year":...}` shapes.
* **VM plumbing**: context uses this registry so `build_room_vm` sets `has_ground`/`ground_item_ids` for the renderer.

#### Item Display Rules
* **Name source**: `ui/item_display.py` uses `catalog.display_name|name|title` when available; else derives by `_`→`-` and Title-Case per hyphen segment.
* **Articles**: `A`/`An` chosen by first alphabetic character (vowel heuristic).
* **Duplicate numbering**: for identical base names on the same tile, append `" (n)"` to the 2nd, 3rd, … occurrence.

### Systems

#### Item Transfers (Get/Drop)
* **Service**: `services/item_transfer.py` centralizes rules and persistence for moving items **ground ↔ inventory**. It enforces **first-match only** (prefix by display name), **INV_CAP=10**, **GROUND_CAP=6**, and the overflow behavior (random item swap) for player commands. **Worn armor is excluded from inventory operations** and is only affected by the `remove` command.
* **Ordering**: Ground display and “first-match” selection use a **stable insertion order** grouped by first-seen display name so duplicates appear adjacent. Inventory order is pickup order (FIFO).
* **Persistence**: Inventory is stored in `state/playerlivestate.json` as `inventory: [iid,...]`. Ground is represented by setting/clearing `pos` on instances in `state/items/instances.json`. All writes use atomic saves.

## IO helpers
- `io/atomic.py` — `atomic_write_json()` and `read_json()` (tmp → fsync → replace).

## Data files (runtime)
- `state/world/2000.json`
- `state/items/catalog.json`, `state/items/instances.json`
- `state/monsters/catalog.json`, `state/monsters/instances.json`
- `state/playerlivestate.json`
- `state/ui/themes/bbs.json`, `state/ui/themes/mono.json`
- `state/logs/game.log`
- `state/runtime/spawn_epoch.json`

## Flow examples
- **look** → dispatch → `RenderPolicy.ROOM` → render_frame → renderer prints.
- **n (locked gate)** → move checks edge → bus.push("MOVE/BLOCKED", "...") → `RenderPolicy.ROOM` → render_frame shows room then a feedback block.
- **combat** (future): compute damage → use monster’s attack template → `bus.push("COMBAT/HIT", "...")` → rendered under `***`.

## Why this split?
- Minimal globals, explicit wiring via context.
- Renderer/formatters pure & snapshot-friendly.
- Commands push messages; REPL paints; logs keep a durable trail.
- Auto-discovery keeps REPL decoupled from command inventory.
## Argument-Command Runner (single & positional)
* **File**: `src/mutants/commands/argcmd.py`.
* **Purpose**: unify empty/invalid/success handling and argument parsing for commands that accept subjects (one or two positional args), reducing per-command boilerplate and preventing regressions.
* **API (single-arg)**:
  - `ArgSpec`: `verb`, `arg_policy`, `messages` (`usage|invalid|success`), `reason_messages`, `success_kind`, `warn_kind`.
  - `run_argcmd(ctx, spec, arg, do_action)`: trims arg; required+empty → usage; else calls `do_action(subject)`; on failure maps reason to message; on success uses `display_name|name|item_name|subject` for `{name}`.
* **API (two-arg)**:
  - `PosArgSpec`: `verb`, `args=[("dir","direction"), ("item","item_in_inventory")]` etc., `messages` (`usage|invalid|success`), `reason_messages`, `success_kind`, `warn_kind`.
  - `run_argcmd_positional(ctx, spec, arg, do_action)`: tokenizes (quotes allowed); validates each arg by kind (`direction`, `item_in_inventory`, `literal('ions')`, `integer_range(min,max)`); missing args → usage; parse errors → reason-coded warn; else call `do_action(**values)`.
* **Adoption**:
  - `get` and `drop` use `run_argcmd`.
  - Future two-arg commands (POINT, THROW, `BUY ions [amount]` at maintenance shops) will use `run_argcmd_positional` with the minimal arg kinds above.
* **Armor rule**: any **inventory** arg-kind excludes worn armor; armor is not targetable by `get/drop/look/throw/point/buy`. Only `remove` operates on the armor slot.

## Router Prefix Rule (new)
* **Rule**: tokens **≥3** letters resolve to the **unique** command whose name (or alias) starts with that prefix; **<3** works only for explicit aliases (by default `n/s/e/w`).
* **Ambiguity**: if multiple commands match the ≥3 prefix, the router warns and does nothing.
