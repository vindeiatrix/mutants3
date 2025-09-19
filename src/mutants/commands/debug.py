from __future__ import annotations

import shlex

from ..registries import items_instances as itemsreg
from ..registries import items_catalog
from ..services import item_transfer as it
from ..services import player_state as pstate
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
    pstate.ensure_active_profile(p, ctx)
    pstate.bind_inventory_to_active_class(p)
    it._ensure_inventory(p)
    inv = p["inventory"]
    for _ in range(count):
        iid = itemsreg.create_and_save_instance(item_id, year, x, y, origin="debug_add")
        itemsreg.clear_position(iid)
        inv.append(iid)
    p["inventory"] = inv
    it._save_player(p)
    itemsreg.save_instances()


def _adjust_ions(ctx, delta: int) -> None:
    """Adjust the active player's ion count by ``delta`` and persist the change."""

    bus = ctx["feedback_bus"]
    result = {"applied": False, "change": 0, "total": 0}

    def _mutate(state, active):
        result["applied"] = True
        current = int(active.get("ions") or 0)
        new_total = max(0, current + delta)
        result["change"] = new_total - current
        result["total"] = new_total
        active["ions"] = new_total

    pstate.mutate_active(_mutate)

    if not result["applied"]:
        bus.push("SYSTEM/ERROR", "No player available to modify ions.")
        return

    change = int(result["change"])
    total = int(result["total"])
    if change > 0:
        bus.push("SYSTEM/OK", f"added {change} ions. (total: {total})")
    elif change < 0:
        bus.push("SYSTEM/OK", f"removed {abs(change)} ions. (total: {total})")
    else:
        bus.push("SYSTEM/INFO", f"Ion total unchanged. (total: {total})")


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
    if not parts:
        ctx["feedback_bus"].push(
            "SYSTEM/INFO", "Usage: debug add <item_id> [qty] | debug ions <amount>"
        )
        return

    if parts[0] == "add":
        debug_add_cmd(" ".join(parts[1:]), ctx)
        return

    if parts[0] in {"ions", "ion"}:
        if len(parts) < 2:
            ctx["feedback_bus"].push("SYSTEM/INFO", "Usage: debug ions <amount>")
            return
        try:
            amount = int(parts[1])
        except ValueError:
            ctx["feedback_bus"].push(
                "SYSTEM/WARN", "Ion amount must be an integer (e.g. 100 or -25)."
            )
            return
        _adjust_ions(ctx, amount)
        return

    ctx["feedback_bus"].push(
        "SYSTEM/INFO", "Usage: debug add <item_id> [qty] | debug ions <amount>"
    )


def register(dispatch, ctx) -> None:
    dispatch.register("debug", lambda arg: debug_cmd(arg, ctx))
    dispatch.register("give", lambda arg: debug_add_cmd(arg, ctx))
