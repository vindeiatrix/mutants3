# Mutants — Dense Architecture Notes (for AI/maintainers)

## Runtime loop (REPL)
- Pattern: **Read → Eval → Print → Loop**.
- File: `repl/loop.py` (metronome). It:
  1) builds the **app context** (`app/context.py`);
  2) creates a **Dispatch** router (`repl/dispatch.py`);
  3) calls `commands.register_all.register_all(dispatch, ctx)` to auto-register all commands;
  4) prints a banner; initial `render_frame(ctx)`;
  5) for each input line: split `token arg`; `dispatch.call(token, arg)`; always `render_frame(ctx)`.

## App context (single source of wiring)
- File: `app/context.py`.
- Holds: `player_state`, `world_loader`, optional `items`/`monsters` registries, `headers`,
  `feedback_bus`, `logsink` (subscribed to bus), `theme` (JSON), `renderer` callable.
- Helpers:
  - `build_context()` returns the dict above.
  - `build_room_vm(ctx)` constructs UI data for current tile (no I/O in renderer).
  - `render_frame(ctx)` builds RoomVM, drains bus, invokes renderer with theme palette/width, prints lines + prompt.

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
  - **does not print**; REPL repaints after dispatch.

## UI stack (pure, testable)
- **ViewModel**: `ui/viewmodels.py` — RoomVM shape consumed by renderer.
- **Formatters**: `ui/formatters.py` — text → tokenized segments (no ANSI).
- **Styles**: `ui/styles.py` — token names + resolver (`resolve_segments`, `tagged_string`).
- **Color Groups**: every formatted text fragment can declare a `group` (dotted string). `styles.resolve_color_for_group(group)` looks up `state/ui/colors.json` with fallback: exact → `prefix.*` → `defaults` → `"white"`. Existing color-by-name calls still work via `styles.colorize_text`.
- **Themes**: `ui/themes.py` — loads JSON `state/ui/themes/<name>.json` → `Theme { palette, width }` (no code changes needed to tweak colors).
- **Wrap**: `ui/wrap.py` — ANSI-aware 80-col wrapping (only list sections wrap).
- **Renderer**: `ui/renderer.py` — orchestrates lines in fixed order:
  Header → Compass → N/S/E/W → `***` → in-room (monsters, ground wrapped) → `***` + feedback lines (if any).
  Renderer uses `Theme.palette` + `Theme.width`.

### Data Flow (UI)
VM → Formatters (build strings + **group**) → Styles (resolve color by group) → Renderer (layout/output)

### UI Contract: Direction List Is Open-Only
* **Invariant:** The direction list must show only *open/continuous* exits (“area continues.”) and must not show blocked entries (terrain/boundary/gates).
* **Implementation (minimal):** The renderer iterates `vm["dirs_open"]` when present; if not present, it filters `vm["dirs"]` to open-only (`edge.base == 0`) before rendering.
* **Guardrail:** With `MUTANTS_DEV=1`, the renderer asserts if a non-open edge appears in `dirs_open`; otherwise it logs a warning and drops it. This prevents downstream refactors (formatting/color) from resurrecting blocked rows.
* **Separation of concerns:** Movement failures should surface via feedback lines (e.g., “You’re blocked!”) rather than as direction rows.

## Feedback and logs (diagnostics)
- `ui/feedback.py` — **Feedback Bus** (structured events):
  - `.push(kind, text, **meta)`; `.drain()`; `.subscribe(listener)`.
  - Common kinds: `SYSTEM/OK|WARN|ERR`, `MOVE/OK|BLOCKED`, `GATE/OPEN|CLOSE|LOCKED|FAIL`, `LOOT/PICKUP|DROP`,
    `COMBAT/HIT|MISS|CRIT|TAUNT`, `SPELL/CAST|FAIL`, `DEBUG/...`.
- `ui/logsink.py` — **Ring buffer** + optional file append to `state/logs/game.log` (ISO timestamp, KIND, TEXT).
- Renderer styles feedback lines by **kind→token** mapping in the theme (e.g., `FEED_BLOCK` bold yellow).

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

## IO helpers
- `io/atomic.py` — `atomic_write_json()` and `read_json()` (tmp → fsync → replace).

## Data files (runtime)
- `state/world/2000.json`
- `state/items/catalog.json`, `state/items/instances.json`
- `state/monsters/catalog.json`, `state/monsters/instances.json`
- `state/playerlivestate.json`
- `state/ui/themes/bbs.json`, `state/ui/themes/mono.json`
- `state/logs/game.log`

## Flow examples
- **look** → dispatch → render_room: VM from context → renderer prints.
- **n (locked gate)** → move checks edge → bus.push("MOVE/BLOCKED", "...") → render_frame shows room then a feedback block.
- **combat** (future): compute damage → use monster’s attack template → `bus.push("COMBAT/HIT", "...")` → rendered under `***`.

## Why this split?
- Minimal globals, explicit wiring via context.
- Renderer/formatters pure & snapshot-friendly.
- Commands push messages; REPL paints; logs keep a durable trail.
- Auto-discovery keeps REPL decoupled from command inventory.
