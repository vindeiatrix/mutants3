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

## Toggling UI Traces (optional future)

We reserved `logs trace ui on|off` for future UI-side traces (e.g., direction list reasoning). It writes similar one-liners with a `UI/DECISION` prefix.

## Files Used

- `state/logs/game.log` — the main log file (already in use by the game).
- `state/runtime/trace.json` — stores your trace toggles (`move`, `ui`).
- `state/world/dynamics.json` — dynamic overlays (temporary barriers / blasted edges).

These are plain JSON or text; safe to inspect or back up.
