# How to Change Colors (UI Color Groups)

This game now uses **semantic color groups** instead of hard-coded color names at print sites. Every piece of text is tagged with a *group* (e.g., `compass.line`, `dir.open`, `room.title`). A single JSON file maps these groups to one of the five colors used by the game: **yellow, green, blue, red, white**.

## TL;DR
Edit **`state/ui/colors.json`** and change the color names in the `"map"` section. No code changes are required.

```json
{
  "defaults": "white",
  "map": {
    "compass.line": "green",
    "dir.open": "yellow",
    "dir.blocked": "red",
    "room.title": "blue",
    "room.desc": "white"
  }
}
```

## Rules & Fallbacks

Resolution order: exact key → prefix wildcard (`"compass.*"`) → `"defaults"` → `"white"`.

If you want to make all compass-related text green, set:

```json
{ "map": { "compass.*": "green" } }
```

(Exact keys take precedence over wildcards if both are present.)

## Frequently Changed Groups

- `compass.line` — the “Compass: (4E : -4N)” line (default: green).
- `dir.open` — lines like `south  - area continues.` (default: yellow).
- `dir.blocked` — lines like `south  - terrain blocks the way.` (default: red).
- `room.title` — the room header/title (default: blue).
- `room.desc` — room description text (default: white).
- `feedback.info`, `feedback.warn`, `feedback.err` — bottom feedback messages.
- `log.line` — text written to `state/logs/game.log` (usually white).

## Advanced: Per-Theme Overrides

By default, colors load from `state/ui/colors.json`. You can point to an alternate file via the environment variable:

```bash
export MUTANTS_UI_COLORS_PATH=/abs/path/to/my_colors.json
```

The file format is identical to `colors.json`. This is useful for quick A/B tests of palettes.

## Safety Tips

- Stick to the five supported color names: yellow, green, blue, red, white.
- If a group is missing from the map, it will inherit from a matching prefix (`group.*`) or fall back to `defaults`.
- Avoid editing code to change colors; edit the JSON instead. The renderer and formatters already tag groups.
