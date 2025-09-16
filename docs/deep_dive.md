What it is

A Python 3.11, terminal (BBS-style) game skeleton with a REPL loop, strong file-backed state, and modular registries for worlds, items, monsters—already wired for movement, inventory, gates, time-travel, menus, theming, logging, and tests.

Entry: python -m mutants → repl.loop.main(); dev help via Makefile (run-once, logs-probe) and pytest.

Startup & runtime

Entrypoint: src/mutants/__main__.py sets logging and runs repl/loop.py::main.

App context (app/context.py): calls bootstrap/runtime.ensure_runtime() to create state/ folders and defaults, discover state/world/*.json (or build a minimal world), prime themes, set up a FeedbackBus, LogSink, Theme, ScreenManager, StateManager, registries, and a world_loader (registries/world.load_year).

Env toggles:

WORLD_DEBUG=1 verbose world logs, WORLD_STRICT=1 fail if no worlds, not auto-create; trace flags via logs trace move|ui on|off (persisted under state/runtime/trace.json).

The main loop (REPL)

Read prompt from repl/prompt.py.

Dispatch through repl/dispatch.Dispatch: case-insensitive, ≥3-char unique prefixes, explicit one-letter aliases (e.g., n/s/e/w). All commands autoloaded via commands/register_all.py.

Execute command modules (see below).

Render: if ctx["render_next"] → build a room VM then render (app/context.build_room_vm → ui/renderer.py), else flush queued feedback events.

Persist: StateManager.save_on_exit() runs on quit.

Core data model

Worlds (registries/world.py):

One JSON per year in state/world/<year>.json with a tile grid: pos=[year,x,y], header_idx, and edges by direction (N/S/E/W).

Edge model: base (0 open, 1 ice, 2 boundary, 3 gate), gate_state (0 open, 1 closed, 2 locked), key_type, spell_block.

Loaded into YearWorld (tile map, bounds, getters/setters, symmetry mirroring for edges); safe mutations forbid editing boundary or off-map edges.

Dynamics overlay (registries/dynamics.py): file-backed runtime effects at state/world/dynamics.json (temporary barriers, blasted edges with TTL + created_at; and persistent locks mirrored on opposite edges). overlay_for() merges these on reads.

Player state layers (state/manager.py, docs/STATE.md):

Template (read-only, shipped) state/playerlivestate.json (order: Thief→Priest→Wizard→Warrior→Mage).

Save (mutable) state/savegame.json with meta, per-class snapshots, active_id, autosave on class switch/exit. Atomic writes via io/atomic.py.

Live runtime (in-memory) managed by StateManager (merge defaults, sanitize types, track pos=[year,x,y], command counting for future autosave interval).

Items:

Catalog (registries/items_catalog.py) from state/items/catalog.json (auto-coerces legacy "yes"/"no" to booleans; adds defaults; validations).

Instances (registries/items_instances.py) in state/items/instances.json (unique instance_id with optional charges, wear, enchant flags).

Services (services/item_transfer.py) are the source of truth for get/drop/throw, capacity, duplicate naming, and passability checks via the edge resolver.

Display (ui/item_display.py) canonicalizes names, applies A/An, de-dups with (1),(2).

Monsters: schemas present; catalogs/instances wired but not heavily used yet.

Movement, gates & passability (engine)

Edge resolver (engine/edge_resolver.py): normalizes edge bases, resolves passability and descriptor (one of: area continues., wall of ice., ion force field., open/closed/locked gate.). Symmetric neighbor checks ensure both sides agree; returns a reason chain useful for logs tracing and for “throw lands here or falls at your feet.”

Commands are consistent with resolver semantics; the UI renderer cross-checks descriptors against resolver output in dev tracing to prevent drift.

UI pipeline & theming

View-model (app/context.build_room_vm → ui/viewmodels.py) includes: header, coords, directional edges, monsters here, ground items, events, flags.

Formatters/Renderer (ui/formatters.py, ui/renderer.py): tokenizes lines (header, compass, directions listing with canonical descriptors, ground block) and maps to a theme palette; no raw strings—everything goes through style tokens and palettes.

Wrap (ui/wrap.py): central wrapper with break_on_hyphens=False, break_long_words=False to avoid ugly hyphen splits; CI guard via scripts/guard_wrap.py and logs probe wrap.

Themes (state/ui/themes/*.json, colors in state/ui/colors.json), with ANSI on/off (theme mono disables color cleanly).

Commands (pattern & highlights)

Pattern: each module exposes register(dispatch, ctx); shared parsing helpers in commands/argcmd.py (single or positional arg specs with reasoned failures).

Navigation: north/south/east/west (commands/move.py) updates StateManager and requests render; blocked moves push feedback with resolver’s reason.

Look (look): peeks one tile using resolver; renders that tile transiently.

Gates: open/close/lock/unlock enforce base kind, gate state, and dynamics locks (mirrored to neighbor).

Inventory: get, drop, inv, throw, point (spend charge on ranged item).

Meta/UX: statistics, theme, logs (tail, trace, probes, verifiers), why (explain resolver decisions), debug/give, quit.

Menus (ui/screens.py, commands/menu.py): class selection screen ↔ in-game, x to return and persist.

Persistence & safety

Atomic JSON writes with fsync/rename; corrupt save backup on load; daily litter reset hook.

Logging to state/logs/game.log via LogSink (ring buffer + disk).

Paths are relative to CWD; themes and catalogs resolve from state/… with sensible fallbacks.

Tests

~50 tests under tests/ covering commands (movement/gates/inventory/statistics), resolver symmetry, items catalog, and wrap diagnostics; Makefile target ci-wrap-check verifies UI wrapping hasn’t regressed.

Mental model (one screenful)
python -m mutants
  └── REPL loop
      ├── Dispatch (auto-register commands)
      ├── App Context
      │   ├── StateManager  (templates ⇄ save ⇄ live)
      │   ├── world_loader  (YearWorld + dynamics overlay)
      │   ├── registries    (items/monsters)
      │   ├── ScreenManager (selection ↔ in-game)
      │   ├── FeedbackBus → LogSink (and stdout)
      │   └── Theme+Styles  → Renderer + Wrap
      └── Commands
          ├── Use services (item_transfer), resolver, registries
          └── Push feedback and/or set render_next

Extension points & “shovel-ready” improvements

Finish the class reset (BURY) in the selection screen and add a confirm flow.

Shops & spenders: implement buy/sell commands; catalog already has values and display helpers.

Combat loop: route through edge resolver + items (ranged/melee), then persist HP/conditions in StateManager; keep it testable with pure functions.

World editing tools: dev commands to toggle edges/headers and dump diffs; ensure symmetry + bounds invariants via YearWorld.

Autosave interval: wire autosave_interval (count-based) already scaffolded in StateManager.

Configurable paths: allow an explicit state_root to avoid CWD gotchas; pass root through ensure_runtime()/context.

Monsters: flesh out spawn rules and encounters; schemas exist—add catalog + instance loaders parallel to items.

CLI entrypoint: add [project.scripts] mutants = mutants.__main__:main for pipx run mutants.

More tests: TTL expiry for dynamics.overlay_for, lock/unlock edge–neighbor mirroring, and error paths (missing tile/world).

UX polish: show ground items inline on move; improve help to include prefix rules and examples (uses repl/help.py already).

Quick run & dev cheatsheet

Run once with probes: make run-once (verifies wrap and logs).

Typical flow:

n/s/e/w, look [dir], open/close/lock/unlock [dir], get|drop <item>, inv, throw <dir> <item>, point <dir> <ranged-item>, statistics, travel <year>, x to return to class menu, quit.

Debugging: logs (tail), logs trace move on, logs probe wrap, logs verify edges.
