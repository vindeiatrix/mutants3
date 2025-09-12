# Mutants — Architecture Overview (Human-Readable)

This is the plain-English tour of how the game starts, reads your input, updates state, and prints what you see.

## Startup
1) `python -m mutants` runs a tiny entrypoint that starts the REPL.
2) The REPL asks the **app context** to build everything it needs.
3) The app context calls `ensure_runtime()`:
   - makes `state/` folders if missing,
   - creates empty `items/instances.json` and `monsters/instances.json` if missing,
   - writes theme JSONs (bbs/mono) if missing,
   - looks for worlds in `state/world/*.json`; if none, creates a minimal world (defaults come from `state/config.json`).
4) Player state is created (or loaded). If the template wants year `2000` but you don’t have it, we pick the **nearest** year that does exist.

## The Game Loop (REPL)
- **Read**: get your command (e.g., `n`).
- **Eval**: a simple router maps `n` to the move handler; the handler uses the world registry to check edges and updates your `(x,y)` if allowed. It doesn’t print— it **pushes a feedback message** like “The gate is locked.”
- **Print**: we build a view of the room (header, compass, directions, ground, etc.), drain any feedback messages, and render everything using the current theme (colors live in JSON).

This repeats each turn.

## Where things live
- **REPL**: `repl/loop.py` (the metronome), `repl/dispatch.py` (command router).
- **Commands**: `commands/*.py` (movement, theme, logs, etc.).
- **App context**: `app/context.py` (wires player state, world loader, renderer, theme, feedback bus).
- **UI**: `ui/renderer.py` (layout), `ui/formatters.py` (phrasing), `ui/themes.py` (loads colors), `ui/styles.py` (token names), `ui/wrap.py` (80-col lists).
- **Color Groups** (new): text fragments are tagged with semantic groups like `compass.line`, `dir.open`, `dir.blocked`, `room.title`, `room.desc`. A single JSON file (`state/ui/colors.json`) maps each group to a color name so palette tweaks require no code edits. `styles.resolve_color_for_group(group)` handles dotted fallback (`compass.line` → `compass.*` → default).
- **Feedback & logs**: `ui/feedback.py` (message queue), `ui/logsink.py` (ring buffer + `state/logs/game.log`).
- **Registries**: `registries/world.py` (maps), `registries/items_*`, `registries/monsters_*`.
- **Bootstrap**: `bootstrap/lazyinit.py` (player), `bootstrap/runtime.py` (state dirs/files, themes, world discovery or minimal world creation).
- **Runtime data**: `state/world/<year>.json`, `state/items/*.json`, `state/monsters/*.json`, `state/ui/themes/*.json`, `state/logs/game.log`.

## Renderer/UI stack (80-col BBS look)

The UI is composed of a view model → formatters → styles/themes → renderer; the feedback bus and logsink feed the bottom block and `state/logs/game.log`.

### Wrapping rules (80 columns)
- UI text wraps at **80 columns** and never splits inside hyphenated tokens like `Ion-Decay`.
- Inventory output (`inv`) shares the same wrapping helper as the ground list so hyphenated names stay intact across lines.

### Color Groups (new)
All text is emitted with a **semantic color group** (e.g., `compass.line`, `dir.open`, `dir.blocked`, `room.title`, `room.desc`). The renderer does **not** pick colors directly. Instead, `src/mutants/ui/styles.py` resolves `group → color` using a colors map (default `state/ui/colors.json`).

### Themes (useful now)
The `theme` command now switches two visual aspects at runtime:
- **Palette source** via `colors_path` in the theme JSON (e.g., `state/ui/colors.json`). The theme command updates the active palette immediately.
- **ANSI on/off** via `ansi_enabled`. When false, all colorization is bypassed for clean transcripts and diffable logs.
`bbs` enables ANSI with the standard palette; `mono` disables ANSI (monochrome). Width/layout remain locked at 80 cols by design.

### UI Contract (navigation frame, minimal lock-in)
We lock the navigation frame now to prevent regressions:
- **Direction descriptors** are a closed set of five strings: `area continues.`, `wall of ice.`, `ion force field.`, `open gate.`, `closed gate.`; see `src/mutants/ui/uicontract.py`.
- **Rendered direction lines** are currently **open-only** (plain tiles) and use the exact format `"{dir:<5} - {desc}"` with two spaces before the dash. The open descriptor is always **`area continues.`**.
- The separator line `***` is inserted only **between** non-empty blocks; never at the start or end of a frame.
- Compass uses the canonical prefix **`Compass: `** (no plus signs on non-negative values).

### Ground Block (locked behavior)
When the VM indicates items are present on the ground, the renderer prints a **Ground block**:
- Header literal: **`On the ground lies:`** (see `uicontract.py`).
- A comma-separated list of items, wrapped to **80 columns**, ending with a period.
- The block is surrounded by single `***` separators: one before (after directions) and one after.
The VM must set `has_ground=True` **only** when `ground_item_ids` is non-empty; otherwise the renderer drops the block and warns (or asserts in dev).

### Monsters & Cues (after Ground)
- **Monsters present:** a single line is emitted:
  - One monster: `"<Name> is here."`
  - Multiple monsters: `"<A>, <B>, and <C> are here with you."` (comma before `and`)
  A single `***` separator precedes this block and another follows it.
- **Cues:** each cue (e.g., `You see shadows to the south.`) prints as a single line; a `***` separator appears **between** multiple cue lines. The VM supplies `cues_lines` already worded; the UI does not invent text.
Placement is fixed: **Room → Compass → Directions → `***` → Ground (optional) → `***` → Monsters (optional) → `***` → Cues (optional)**. This matches the original captures’ section order.

### Separators (hard rule)
- The separator line `***` appears **only between** non-empty blocks, never at the start or end of a frame.
- Blocks are: **(A)** Room+Compass+Directions, **(B)** Ground (if any), **(C)** Monsters (if any), **(D)** Cues (if any).  
  The renderer first builds these blocks, then **joins** them with a single separator between adjacent blocks.  
  Inside the **Cues** block, separators appear **between** multiple cue lines, not after the last.

## Daily Litter Spawns (once-per-day reset)
At startup (once per calendar day), the game performs a **litter reset**:
- Removes only items previously spawned by the system (`origin: "daily_litter"`).
- Spawns a fixed number per year (`state/items/spawn_rules.json: daily_target_per_year`) of catalog items marked `"spawnable": true`, using per-item weights and optional per-year caps.
- Placement rules: iterates world tiles (`tile["pos"] = [year,x,y]`) and never exceeds six items per tile; capped items (already at limit for a year) are skipped.
- The reset is deterministic for the day (seeded by date) and runs only at startup, so no mid-day pop-in.

### Ground items plumbing (minimal)
- The **items registry** exposes `list_at(year,x,y)` which reads `state/items/instances.json` (recognizing both nested `pos` and flat `year/x/y` shapes) and resolves display names via the catalog.
- The **room VM** sets `has_ground` and `ground_item_ids`; the renderer formats names with the **Item Display** rules (Title Case, hyphens, `A/An`, duplicate numbering) and shows the Ground block when non-empty.

### Inventory & Transfers
- Inventory is an **ordered list of instance IDs** in `state/playerlivestate.json`; worn armor lives separately and isn't counted.
- `get <prefix>` picks the **first matching** ground item (by display-name prefix). If this pushes inventory over **10**, a random inventory item falls to the ground (overflow, swapping with a random ground item if the tile already has six).
- `drop <prefix>` drops the first matching inventory item (pickup order, excluding worn armor). If ground exceeds **6**, a random ground item pops into inventory and may drop another if inventory would exceed 10.
- `inv` prints inventory with the same naming rules as the ground list.

## Item Display (canonical names)
- Display names come from the catalog (`display_name`/`name`) or are derived from the item ID by replacing `_` with `-` and Title-Casing each part (e.g., `ion_decay` → `Ion-Decay`).
- The ground list prefixes each name with `A`/`An` (vowel heuristic) and numbers duplicates as ` (1)`, ` (2)`, … for subsequent identical items.

## Future-proofing choices
- No hard-coded year: world **discovery** + **nearest year** when needed.
- Themes are JSON so you can change colors without code.
- Feedback messages are structured and rendered in a distinct block—easy to spot and log.
- Adding more years/monsters/items just means dropping more JSON—no code edits.

That’s the system in a nutshell. If it prints weird, try `theme mono`; if commands seem ignored, check `log`; and if a template’s start year doesn’t exist, the runtime will map it for you.
## Passability Engine (single source of truth)
Movement decisions and (optionally) direction descriptors are determined by a single resolver at `src/mutants/engine/edge_resolver.py`. It layers:
- **Base terrain** (world edge `base`), **gates** (open/closed), then **dynamic overlays** (temporary barriers/blasted edges from `state/world/dynamics.json`), and **actor modifiers** (e.g., rods/keys).
It returns `passable` and a canonical descriptor (one of: `area continues.`, `wall of ice.`, `ion force field.`, `open gate.`, `closed gate.`), plus an internal reason chain for debugging.

### UI direction guard (dev-safe)
The renderer now cross-checks each printed direction with the same passability resolver. If the resolver says a direction is blocked, the UI silently drops that row (and in `MUTANTS_DEV=1` asserts), keeping UI and movement in lockstep.

## In-game tracing
Use `logs trace move on|off` (and later `logs trace ui on|off`) to toggle a lightweight trace. With move tracing on, each attempted move logs a one-line JSON decision to `state/logs/game.log`. Use `why <dir>` to print the current tile’s decision chain and descriptor for that direction.

### Edge sampler
`logs verify edges [count]` randomly samples open tiles in the current year and checks **cur→dir** vs **neighbor→opp** symmetry with the resolver, logging any mismatches to the game log and printing a summary in-game.
