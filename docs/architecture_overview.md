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

## Future-proofing choices
- No hard-coded year: world **discovery** + **nearest year** when needed.
- Themes are JSON so you can change colors without code.
- Feedback messages are structured and rendered in a distinct block—easy to spot and log.
- Adding more years/monsters/items just means dropping more JSON—no code edits.

That’s the system in a nutshell. If it prints weird, try `theme mono`; if commands seem ignored, check `log`; and if a template’s start year doesn’t exist, the runtime will map it for you.
