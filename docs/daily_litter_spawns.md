# Daily Litter Spawns — How it Works & How to Tune It

This system recreates the old BBS “daily reset”: once per calendar day (on startup), it **removes yesterday’s litter** and **spawns new items** on the ground. Nothing pops in mid-day.

## What Spawns (and How Often)

- **Spawnable items** are defined in `state/items/catalog.json` by adding `"spawnable": true` on the catalog entry.
- Optional spawn tuning per item (inside the same catalog entry):
  ```json
  {
    "spawnable": true,
    "spawn": { "weight": 12, "cap_per_year": 40 }
  }
  ```
  `weight` (default 1) is the relative likelihood versus other spawnables.
  `cap_per_year` (optional) is a hard limit per year on how many of this item can exist on the ground after reset. If players’ items already exceed the cap, no new copies spawn that day for that year.

## Global Spawn Rules

`state/items/spawn_rules.json`:

```json
{
  "daily_target_per_year": 120,
  "max_ground_per_tile": 6
}
```

- `daily_target_per_year`: total items to place per year each day (spread across spawnable items by weight).
- `max_ground_per_tile`: maximum items allowed on a single tile; the spawner never exceeds this, picking another tile if necessary.
- Years are treated equally; we do not vary by year.

## Placement Rules

- **Open tiles only:** the spawner selects from open tiles reported by the world registry; blocked tiles are ignored.
- **Ground capacity respected:** the spawner keeps a per-tile counter and skips any tile at capacity; it will not place the 7th item.
- **Multiple spawnables may land on the same tile** if space remains; there is no one-item-per-tile restriction.

## Reset Timing (No Mid-Day Pop-In)

On the first startup each calendar day, the spawner runs:

1. Remove yesterday’s litter only (instances with `origin: "daily_litter"`), leaving player drops intact.
2. Spawn up to `daily_target_per_year` items per year using weights & caps.
3. Save instances and record the date in `state/runtime/spawn_epoch.json`.
4. Subsequent restarts that same day do nothing (idempotent).

The RNG seed is the `YYYY-MM-DD` date string, so placement is deterministic for the day.

## How to Adjust

**Make an item spawnable / adjust prevalence**

Edit `state/items/catalog.json` on the item's entry:

- Add `"spawnable": true` to include it.
- Add `"spawn": {"weight": 8}` to make it more common (lower weight → rarer).
- Add `"spawn": {"cap_per_year": 25}` to limit how many can exist per year after reset.

**Change the daily volume or tile capacity**

Edit `state/items/spawn_rules.json`:

- Increase/decrease `daily_target_per_year` to change total items per year.
- Adjust `max_ground_per_tile` if ground capacity limits change.

## Safety & Guarantees

- The spawner never exceeds 6 items per tile; it checks capacity before adding an instance.
- If an item already meets its `cap_per_year` from player drops, no more are spawned.
- Only instances tagged with `origin: "daily_litter"` are removed during reset; all other items remain.
- Missing files or worlds cause a skip with a log warning, but do not block startup.

## Troubleshooting

- **“No litter spawned today”**: ensure `catalog.json` entries have `"spawnable": true` and `daily_target_per_year > 0`; confirm `spawn_epoch.json` reflects today’s date.
- **“Too many of one item”**: lower its `weight` and/or set a `cap_per_year`.
