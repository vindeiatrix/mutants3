from __future__ import annotations

import shlex

from ..registries import items_instances as itemsreg
from ..registries import items_catalog
from ..services import item_transfer as it
from ..util.textnorm import normalize_item_query


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx.get("player_state", {})
    aid = state.get("active_id")
    for pl in state.get("players", []):
        if pl.get("id") == aid:
            pos = pl.get("pos") or [0, 0, 0]
            return int(pos[0]), int(pos[1]), int(pos[2])
    pos = state.get("players", [{}])[0].get("pos") or [0, 0, 0]
    return int(pos[0]), int(pos[1]), int(pos[2])


def _display_name(it: dict) -> str:
    for key in ("display_name", "name", "title"):
        if isinstance(it.get(key), str):
            return it[key]
    return it.get("item_id", "")


def _resolve_item_id(raw: str, catalog):
    q = normalize_item_query(raw)
    q_id = q.replace("-", "_")
    if catalog.get(q_id):
        return q_id, None
    prefix = [iid for iid in catalog._by_id if iid.startswith(q_id)]
    if len(prefix) == 1:
        return prefix[0], None
    if len(prefix) > 1:
        return None, prefix
    name_matches = []
    for it in catalog._items_list:
        if normalize_item_query(_display_name(it)) == q:
            name_matches.append(it["item_id"])
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        return None, name_matches
    return None, []



def _add_to_inventory(ctx, item_id: str, count: int) -> None:
    """Create *count* instances of item_id and add them to the active player's inventory."""
    year, x, y = _pos_from_ctx(ctx)
    p = it._load_player()
    it._ensure_inventory(p)
    inv = p["inventory"]
    for _ in range(count):
        iid = itemsreg.create_and_save_instance(item_id, year, x, y, origin="debug_add")
        itemsreg.clear_position(iid)
        inv.append(iid)
    p["inventory"] = inv
    it._save_player(p)
    itemsreg.save_instances()


def debug_add_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    bus = ctx["feedback_bus"]
    if not parts:
        bus.push("SYSTEM/INFO", "Usage: debug add <item_id> [qty]")
        return
    catalog = items_catalog.load_catalog()
    item_arg = parts[0]
    item_id, matches = _resolve_item_id(item_arg, catalog)
    if not item_id:
        if matches:
            bus.push(
                "SYSTEM/WARN",
                f"Ambiguous item ID: \"{item_arg}\" matches {', '.join(matches)}.",
            )
        else:
            bus.push("SYSTEM/WARN", f"Unknown item: {item_arg}")
        return
    try:
        count = int(parts[1]) if len(parts) >= 2 else 1
    except Exception:
        count = 1
    count = max(1, min(99, count))
    _add_to_inventory(ctx, item_id, count)
    bus.push("DEBUG", f"added {count} x {item_id} to inventory.")


def debug_cmd(arg: str, ctx):
    parts = shlex.split(arg.strip())
    if parts and parts[0] == "add":
        debug_add_cmd(" ".join(parts[1:]), ctx)
        return
    bus = ctx["feedback_bus"]
    bus.push("SYSTEM/INFO", "Usage: debug add <item_id> [qty]")


def register(dispatch, ctx) -> None:
    dispatch.register("debug", lambda arg: debug_cmd(arg, ctx))
    dispatch.register("give", lambda arg: debug_add_cmd(arg, ctx))
