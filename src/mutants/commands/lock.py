from __future__ import annotations

from typing import Any, Dict

from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog
from mutants.util.directions import OPP, DELTA

from .argcmd import coerce_direction
from ._util.items import resolve_item_arg


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return (state.get("players") or [{}])[0]


USAGE = (
    "Usage: lock <direction> <key name>\n"
    "Examples: lock west devil-key | loc w d"
)


def lock_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    bus = ctx["feedback_bus"]
    subject = (arg or "").strip()
    if not subject:
        bus.push("SYSTEM/WARN", USAGE)
        return

    parts = subject.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bus.push("SYSTEM/WARN", USAGE)
        return

    dir_token, key_query = parts[0], parts[1].strip()
    direction = coerce_direction(dir_token)
    if not direction:
        bus.push("SYSTEM/WARN", "Try north, south, east, or west.")
        return

    key_iid = resolve_item_arg(ctx, key_query)
    if not key_iid:
        bus.push("SYSTEM/WARN", f"You're not carrying a {key_query}.")
        return

    inst = itemsreg.get_instance(key_iid) or {}
    cat = items_catalog.load_catalog()
    tpl = cat.get(inst.get("item_id")) or {}
    if not tpl.get("key"):
        bus.push("SYSTEM/WARN", "You need a key to lock a gate.")
        return

    decision = _lock_gate(ctx, direction, tpl.get("key_type") or "")
    if not decision.get("ok"):
        reason = decision.get("reason") or "invalid"
        msg = {
            "not_gate": "You can only lock a closed gate.",
            "already_open": "You can only lock a closed gate.",
            "already_locked": "The gate is already locked.",
            "no_key": "You need a key to lock a gate.",
        }.get(reason)
        bus.push("SYSTEM/WARN", msg or "Nothing happens.")
        return

    bus.push("SYSTEM/OK", f"You lock the gate {direction}.")


def _lock_gate(ctx: Dict[str, Any], direction: str, key_type: str) -> Dict[str, Any]:
    # Use active player and check both sides of the edge.
    p = _active(ctx["player_state"])
    year, x, y = p.get("pos", [0, 0, 0])
    D = direction[0].upper()
    world = ctx["world_loader"](year)
    tile = world.get_tile(x, y) or {}
    edge = (tile.get("edges") or {}).get(D, {}) or {}
    base = edge.get("base", 0)
    gs = edge.get("gate_state", 0)

    # Also consider the opposite edge from the neighbouring tile so we
    # correctly report gates that only have their geometry on that side.
    dx, dy = DELTA.get(D.lower(), (0, 0))
    opp = OPP.get(D.lower(), D.lower()).upper()
    nbr = world.get_tile(x + dx, y + dy) or {}
    nedge = (nbr.get("edges") or {}).get(opp, {}) or {}
    nbase = nedge.get("base", 0)
    ngs = nedge.get("gate_state", 0)

    if not (base == BASE_GATE or nbase == BASE_GATE):
        return {"ok": False, "reason": "not_gate"}
    if gs == 0 and ngs == 0:
        return {"ok": False, "reason": "already_open"}
    lock_meta = dyn.get_lock(year, x, y, D)
    if lock_meta or gs == 2 or ngs == 2:
        return {"ok": False, "reason": "already_locked"}
    if not key_type:
        return {"ok": False, "reason": "no_key"}
    dyn.set_lock(year, x, y, D, key_type)
    return {"ok": True, "dir": direction}


def register(dispatch, ctx) -> None:
    dispatch.register("lock", lambda arg: lock_cmd(arg, ctx))
    dispatch.alias("loc", "lock")

