state/playerlivestate.json — per-class data (active_id, each class’s pos=[year,x,y], inventory=[iid,…], stats, ions, etc.).

Invariant (should be): if an item IID is listed in any player’s inventory, that instance is not on the ground anywhere.

state/items/instances.json — every item instance in the world.

Ground items must have a single location field: pos={"year":Y,"x":X,"y":Y}.

Inventory items must not have any location (pos absent/None; legacy year/x/y absent).

Invariant (should be): an IID is either “on the ground” or “in some inventory,” never both.

state/items/catalog.json — static item templates (name, weight, charges, etc.).

state/world/YYYY.json — map geometry only (terrain, walls, exits). It should not be a second source of loot once the game is running.

In-memory registries & caches

Items registry (items_instances.py)

Keeps an in-memory cache (_CACHE) of instances.json to avoid re-reading every time.

API examples: list_ids_at(year,x,y), get_instance(iid), set_position(iid,...), clear_position(iid), create_and_save_instance(...).

Risk: if any mutator writes instances.json but doesn’t invalidate _CACHE, readers can see stale ground contents; conversely, if some callers bypass the cache and read from disk, you get split-brain: UI sees one thing, pickup code sees another.

Player state service (player_state.py)

Loads/saves the whole playerlivestate.json.

Safe path: mutate_active(fn) → atomically read, mutate just the active player, write back.

Risk: older code paths that manually merged dicts sometimes wrote to the wrong player slot or left a stray top-level inventory key.

Daily litter / spawners

Logic that spawns items for the “day” or on visiting.

Safe model: they should materialize into instances.json only.

Risk: if rendering also consults a spawner list in addition to instances, items can appear again after pickup (a second source).

Rendering + commands (the flow)

Room view (“On the ground lies…”)

Get the player’s current pos (from playerlivestate.json via in-memory state).

Ask the items registry for list_ids_at(year,x,y).

Turn IIDs into catalog names for display.

If this view is ever augmented by another source (e.g., “world loot” or a stale list), you’ll see ghosts.

get <abbrev>

Re-derive the same tile-scoped IID set as the renderer.

Disambiguate the abbrev using catalog names.

Move the chosen IID: remove all location fields from the instance; append IID to active player’s inventory.

Save both registries (instances + player state) and invalidate caches.

If steps 1 & 2 don’t use the same authoritative list the renderer used, or step 3 doesn’t scrub all location fields, ghosts happen.

drop

Mirror of get: ensure the instance gets a single pos dict (no legacy year/x/y), remove from inventory, save, invalidate cache.

Where bugs came from (themes)

Two sources of ground truth

Renderer sometimes combined instances + a spawner/world view. After pickup, the items were removed from instances, but the other path still re-listed them when you walked back: “ghost items.”

Cache vs. disk divergence

Some reads used _CACHE(), others used a raw file read. Some writes didn’t clear _CACHE. Result: pickup path and render path disagreed.

Dual encodings for location

Instances had both pos={...} and legacy top-level year/x/y. If pickup only cleared pos but left year/x/y, the renderer that still looked at legacy fields would think the item was on the ground.

Write-to-wrong-player edge cases

Manual merges in earlier save paths sometimes updated players[0] or the wrong slot; later, inventories looked “merged” across classes.

Context not refreshed after big moves (e.g., travel)

If we updated disk but didn’t refresh the in-memory context, the next command could be computed against old coordinates or old cache.

Principles to stabilize (before re-adding 2100/travel)

One source of truth for ground loot: the only thing the renderer and get consult is instances.json (via the registry). World files and spawners must write to instances, not feed the UI directly.

One encoding for position: instances on the ground have pos={year,x,y}; in inventory have no pos and no legacy year/x/y. Add a tiny helper that always scrubs all ground fields on pickup.

One way to mutate player state: always use player_state.mutate_active(fn); never write playerlivestate.json by hand or fall back to “first player.”

Cache invalidation is mandatory: every instance mutation (set_position, clear_position, create/remove, pickup/drop) must reset _CACHE (or switch to read-through and drop the cache entirely for those calls).

Tile-scoped selection: get builds candidates from list_ids_at(year,x,y) only; no global fuzzy search that can “match” an item elsewhere.

Atomic saves: when pickup/drop happens, persist instances and player state as one logical action (both saved, then caches invalidated, then context refreshed).

Boot-time scrub (safety net): on startup, scan instances: if an IID is in any inventory, strip any pos / legacy coords on that instance. (Heals old saves and prevents year-specific oddities from lingering.)

Invariant checks (debug): add debug items-audit that reports:

any instance that has both pos and is in an inventory,

any instance with legacy top-level year/x/y,

player input
   ↓
command (get/drop/move/etc.)
   ↓
services (player_state, item_transfer)
   ↓             ↓
playerlivestate.json   instances.json   <-- SINGLE source for ground
        ↑                   ↑
        └──── save + invalidate caches ────┘
                      ↓
             in-memory registries
                      ↓
                 renderer (room)

When we reintroduce 2100 & travel

Travel only updates the active player’s pos; it does not touch instances.

After travel, refresh in-memory state so renderer uses the new tile.

Keep room rendering and get strictly tied to instances; spawners for 2100 should materialize items into instances (once) and never feed the UI directly.

any tile where renderer sees an IID that get wouldn’t pick.
