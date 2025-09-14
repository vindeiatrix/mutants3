from __future__ import annotations

from typing import Any, Dict, Optional

from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog

from .argcmd import PosArg, PosArgSpec, run_argcmd_positional


def _has_any_key(ctx: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Return (has_key, key_type) for first key in inventory."""
    cat = items_catalog.load_catalog()
    p = ctx["player_state"]
    inv = (p.get("players") or [{}])[0].get("inventory") or []
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
            "no_key": "You need a key to lock a gate.",
        },
    )

    def action(dir: str) -> Dict[str, Any]:
        p = ctx["player_state"]["players"][0]
        year, x, y = p.get("pos", [0, 0, 0])
        D = dir[0].upper()
        world = ctx["world_loader"](year)
        tile = world.get_tile(x, y) or {}
        edge = (tile.get("edges") or {}).get(D, {})
        base = edge.get("base", 0)
        gs = edge.get("gate_state", 0)
        if base != BASE_GATE:
            return {"ok": False, "reason": "not_gate"}
        if gs == 0:
            return {"ok": False, "reason": "already_open"}
        has_key, key_type = _has_any_key(ctx)
        if not has_key:
            return {"ok": False, "reason": "no_key"}
        dyn.set_lock(year, x, y, D, key_type or "")
        return {"ok": True, "dir": dir}

    run_argcmd_positional(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("lock", lambda arg: lock_cmd(arg, ctx))
    dispatch.alias("loc", "lock")

