from __future__ import annotations

from typing import Any, Dict, Optional

from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog
from ..services import item_transfer as it  # source of truth for player inventory
from mutants.services import player_state as pstate
from mutants.util.directions import OPP, DELTA

from .argcmd import PosArg, PosArgSpec, run_argcmd_positional


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return (state.get("players") or [{}])[0]


def _has_any_key(ctx: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Return (has_key, key_type) by scanning the live player state."""
    cat = items_catalog.load_catalog()
    p = it._load_player()  # live inventory (same source as GET/DROP/THROW)
    pstate.ensure_active_profile(p, ctx)
    pstate.bind_inventory_to_active_class(p)
    it._ensure_inventory(p)
    inv = p.get("inventory") or []
    for iid in inv:
        inst = itemsreg.get_instance(iid) or {}
        item_id = inst.get("item_id")
        meta = cat.get(item_id) if cat else None
        if isinstance(meta, dict) and meta.get("key") is True:
            return True, meta.get("key_type") or ""
    return False, None


def lock_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    spec = PosArgSpec(
        verb="LOCK",
        args=[PosArg("dir", "direction")],
        messages={
            "usage": "Type LOCK [direction].",
            "success": "You lock the gate {dir}.",
        },
        reason_messages={
            "not_gate": "You can only lock a closed gate.",
            "already_open": "You can only lock a closed gate.",
            "already_locked": "The gate is already locked.",
            "no_key": "You need a key to lock a gate.",
        },
    )

    def action(dir: str) -> Dict[str, Any]:
        # Use active player and check both sides of the edge.
        p = _active(ctx["player_state"])
        year, x, y = p.get("pos", [0, 0, 0])
        D = dir[0].upper()
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
        has_key, key_type = _has_any_key(ctx)
        if not has_key:
            return {"ok": False, "reason": "no_key"}
        dyn.set_lock(year, x, y, D, key_type or "")
        return {"ok": True, "dir": dir}

    run_argcmd_positional(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("lock", lambda arg: lock_cmd(arg, ctx))
    dispatch.alias("loc", "lock")

