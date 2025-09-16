from __future__ import annotations

from typing import Any, Dict, Optional

from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog
from mutants.services.player_source import get_active_player

from .argcmd import PosArg, PosArgSpec, run_argcmd_positional


def _has_matching_key(ctx: Dict[str, Any], required: Optional[str]) -> tuple[bool, bool]:
    """Return (has_any_key, matches_required)."""
    cat = items_catalog.load_catalog()
    player = get_active_player(ctx)
    inv = player.get("inventory") if hasattr(player, "get") else []
    if not isinstance(inv, list):
        inv = list(inv or [])
    has_any = False
    for iid in inv:
        inst = itemsreg.get_instance(iid) or {}
        item_id = inst.get("item_id")
        meta = cat.get(item_id) if cat else None
        if isinstance(meta, dict) and meta.get("key") is True:
            has_any = True
            ktype = meta.get("key_type")
            if required is None or ktype == required:
                return True, True
    return has_any, False


def unlock_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    spec = PosArgSpec(
        verb="UNLOCK",
        args=[PosArg("dir", "direction")],
        messages={
            "usage": "Type UNLOCK [direction].",
            "success": "You unlock the gate {dir}.",
        },
        reason_messages={
            "not_gate": "You can only unlock a locked gate.",
            "not_locked": "That gate isn't locked.",
            "no_key": "You don't have a key.",
            "wrong_key": "That key doesn't fit.",
        },
    )

    def action(dir: str) -> Dict[str, Any]:
        player = get_active_player(ctx)
        pos_raw = player.get("pos") if hasattr(player, "get") else None
        if not isinstance(pos_raw, (list, tuple)):
            pos = [0, 0, 0]
        else:
            pos = list(pos_raw) + [0, 0, 0]
        try:
            year = int(pos[0])
        except Exception:
            year = 0
        try:
            x = int(pos[1])
        except Exception:
            x = 0
        try:
            y = int(pos[2])
        except Exception:
            y = 0
        D = dir[0].upper()
        world = ctx["world_loader"](year)
        tile = world.get_tile(x, y) or {}
        edge = (tile.get("edges") or {}).get(D, {})
        base = edge.get("base", 0)
        gs = edge.get("gate_state", 0)

        lock_meta = dyn.get_lock(year, x, y, D)
        locked = False
        required: Optional[str] = None
        if lock_meta:
            locked = True
            lt = lock_meta.get("lock_type")
            required = lt if lt else None
        elif gs == 2:
            locked = True
            lt = edge.get("key_type")
            required = str(lt) if lt is not None and str(lt) != "" else None

        if base != BASE_GATE:
            return {"ok": False, "reason": "not_gate"}
        if not locked:
            return {"ok": False, "reason": "not_locked"}

        has_any, matches = _has_matching_key(ctx, required)
        if not has_any:
            return {"ok": False, "reason": "no_key"}
        if not matches:
            return {"ok": False, "reason": "wrong_key"}

        if lock_meta:
            dyn.clear_lock(year, x, y, D)
        else:
            world.set_edge(x, y, D, gate_state=1, key_type=None, force_gate_base=True)
            world.save()

        return {"ok": True, "dir": dir}

    run_argcmd_positional(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("unlock", lambda arg: unlock_cmd(arg, ctx))
    for a in ["un", "unl", "unlo", "unloc"]:
        dispatch.alias(a, "unlock")

