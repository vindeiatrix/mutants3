# Logging & Tracing Guide

This game writes standard logs to `state/logs/game.log`. You can now enable lightweight **decision traces** from inside the game, and you can ask **why** a direction is (not) traversable.

## Quick Commands

- **Enable move tracing** (logs one line per attempted move):

```
logs trace move on
```

Disable:

```
logs trace move off
```

- **Explain a direction from here** (prints to the bottom feedback area):

```
why n
why south
```

You’ll see output like:

```
N: wall of ice. | passable=False | base=base:ice; overlay=barrier:blastable
```

- Verify edges across the map (quick symmetry/consistency check):

```
logs verify edges

logs verify edges 200 # sample more tiles
```

This samples random open tiles in your current year and checks the resolver’s two-sided decision (cur→dir vs neighbor→opp). It logs any mismatches to state/logs/game.log as VERIFY/EDGE lines and prints a short summary in-game.

- Verify separator rules (no trailing/leading, no doubles):

```
logs verify separators
```

This runs several scenarios through the renderer’s block joiner. If issues are found, they are logged as VERIFY/SEPARATORS - ... in state/logs/game.log, and a warning is shown in-game.

- Verify item naming rules (A/An, hyphens, numbering):

```
logs verify items
```

Runs deterministic cases like ["ion_decay","skull","skull","opal_knife"] and checks the exact ground-line string. Failures log the expected vs. actual line.

- **Verify get/drop core** (sanity path):

```
logs verify getdrop
```

Executes a deterministic core path through the transfer layer (seeded RNG) to exercise overflow/swap logic. For full end-to-end checks, use manual play with ground at capacity and inventory near the cap.

### Feedback kinds (GET/DROP — updated)
- On **success**, `get` pushes `LOOT/PICKUP` and `drop` pushes `LOOT/DROP` with explicit item names (e.g., “You pick up the Skull.” / “You drop the Skull.”).
- On **invalid/empty**, commands push `SYSTEM/WARN` with usage or reason-mapped messages (e.g., “There isn’t a zz here.”, “You’re not carrying a zz.”, “You have nothing to drop.”).

- **Tail log file inside the game**:

```
logs tail [N]  # default 100
```

Prints the last `N` lines of `state/logs/game.log`.

### Diagnosing text wrapping

Enable tracing:

```
logs trace ui on
```

Run a synthetic probe:

```
logs probe wrap --count 16 --width 80
```

Create a long ground list to force wrapping and inspect the logged payload:

```
debug add item nuclear_decay 12
debug add item bottle_cap 12
look
logs tail 200
```

When tracing is on, the renderer logs both the **raw ground line** and the
**post-wrap lines** with the active wrapper options, for example:

- `SYSTEM/INFO - UI/GROUND raw="On the ground lies: A Nuclear-Decay, …"`
- `SYSTEM/INFO - UI/GROUND wrap width=80 opts={...} lines=["…", "…"]`

Final display strings replace ASCII `-` with U+2011 (no-break hyphen) and bind
leading articles with U+00A0 (non-breaking space). These code points may not be
obvious in your terminal, but they prevent hyphen or article splits. Terminal
panes narrower than 80 columns may visually re-wrap the output and split at
ASCII `-`, but the `lines=[...]` payload is authoritative.

Disable tracing when done:

```
logs trace ui off
```

## Debug helpers
- **Add items to current tile** (for quick setup while testing):
  ```
  debug add item <item_id> [count]
  ```
  Places one or more instances of `<item_id>` at your current coordinates. Useful to check wrapping of hyphenated names and inventory/ground overflow behavior quickly.

## What Tracing Logs

When `move` tracing is on, each attempt adds a single line to `state/logs/game.log`, e.g.:

```
MOVE/DECISION {"pos":"(-15E : -3N)","dir":"S","passable":false,"desc":"ion force field.","why":[["base","base:force"],["gate","gate:closed"]]}
```

This comes from the **Passability Engine**, which layers:
1. **Base** terrain (`base=0 open`, `1 terrain block`, `2 boundary`, `3 gate`),
2. **Gates** (open/closed/locked),
3. **Dynamic overlays** (`barrier`/`blasted` with TTL) from `state/world/dynamics.json`,
4. **Actor** modifiers (e.g., rods/keys).

The first matching layer decides `passable` and the **descriptor**; `why` records the chain.

## Toggling UI Traces

`logs trace ui on|off` toggles UI-side tracing. When enabled, ground rendering logs the raw items string and the wrapped lines with the effective wrapper options. Use this to diagnose hyphen wrapping behavior.

## Files Used

- `state/logs/game.log` — the main log file (already in use by the game).
- `state/runtime/trace.json` — stores your trace toggles (`move`, `ui`).
- `state/world/dynamics.json` — dynamic overlays (temporary barriers / blasted edges).

These are plain JSON or text; safe to inspect or back up.

## Hyphen Wrap Diagnostics (ground truth logs)

When debugging text wrapping, enable UI tracing and use the probe:

```
logs trace ui on
logs probe wrap --count 24 --width 80
logs tail 200
```

You’ll see diagnostics like:
- `SYSTEM/INFO - UI/PROBE raw="On the ground lies: ..."`
- `SYSTEM/INFO - UI/PROBE wrap width=80 opts={...} lines=[ "...", "..." ]`
- `SYSTEM/OK - UI/WRAP/OK` (or `SYSTEM/WARN - UI/WRAP/BAD_SPLIT ...`)

For real game paths, force a long ground list:

```
debug add item nuclear_decay 12
debug add item bottle_cap 12
look
logs tail 200
```

This logs:
- `SYSTEM/INFO - UI/GROUND raw="..."`
- `SYSTEM/INFO - UI/GROUND wrap width=80 opts={...} lines=[ ... ]`

**Interpretation:**  
- If `lines=[…]` shows no line ending in `Nuclear-`/`Bottle-`, the engine’s wrap is correct. If your terminal pane is narrower than 80 columns, it may visually re-wrap anyway; trust the logged `lines=[…]` for ground truth.

**Invariant implemented:**  
- Final display strings (after article “A/An ” and any numbering “(n)”) are hardened: ASCII `-` → U+2011 (no-break hyphen), and the article space → U+00A0 (NBSP). With `break_on_hyphens=False` and `break_long_words=False`, hyphenated tokens will not split.
