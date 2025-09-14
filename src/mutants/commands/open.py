from __future__ import annotations

from typing import Any, Dict

from mutants.registries.world import BASE_GATE
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg, items_catalog

from .argcmd import coerce_direction


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def register(dispatch, ctx) -> None:
    bus = ctx["feedback_bus"]
    logsink = ctx.get("logsink")

    def _has_key_type_in_inventory(key_type: str) -> bool:
        cat = items_catalog.load_catalog()
        p = _active(ctx["player_state"])
        inv = p.get("inventory") or []
        for iid in inv:
            inst = itemsreg.get_instance(iid) or {}
            item_id = inst.get("item_id")
            meta = cat.get(item_id) if cat else None
            if (
                isinstance(meta, dict)
                and meta.get("key") is True
                and meta.get("key_type") == key_type
            ):
                return True
        return False

    def cmd(arg: str) -> None:
        token = (arg or "").strip().split()
        if not token:
            bus.push("SYSTEM/INFO", "Type OPEN [direction] to open a gate.")
            return
        dir_full = coerce_direction(token[0])
        if not dir_full:
            bus.push("SYSTEM/WARN", f"Unknown direction: {token[0]}")
            return
        D = dir_full[0].upper()

        p = _active(ctx["player_state"])
        year, x, y = p.get("pos", [0, 0, 0])
        world = ctx["world_loader"](year)
        tile = world.get_tile(x, y)
        if not tile:
            bus.push("SYSTEM/WARN", "Current tile not found.")
            return
        edge = (tile.get("edges") or {}).get(D, {}) or {}
        base = edge.get("base", 0)
        gs = edge.get("gate_state", 0)

        if base != BASE_GATE:
            bus.push("SYSTEM/WARN", "There is no gate to open that way.")
            return

        lock_meta = dyn.get_lock(year, x, y, D)
        required_key = None
        if lock_meta:
            required_key = lock_meta.get("lock_type")
        elif gs == 2:
            required_key = edge.get("key_type")
            if required_key is None:
                required_key = ""

        if gs == 0 and not lock_meta:
            bus.push("SYSTEM/INFO", f"The {dir_full} gate is already open.")
            return

        if required_key is not None:
            if not _has_key_type_in_inventory(str(required_key)):
                bus.push("SYSTEM/WARN", "The gate is locked.")
                return
            if lock_meta:
                dyn.clear_lock(year, x, y, D)
            else:
                world.set_edge(x, y, D, key_type=None)

        world.set_edge(x, y, D, gate_state=0, force_gate_base=True)
        world.save()

        bus.push("SYSTEM/OK", f"You've just opened the {dir_full} gate.")
        if logsink:
            logsink.handle({
                "ts": "",
                "kind": "GATE/OPEN",
                "text": f"{{\"pos\":\"({x}E : {y}N)\",\"dir\":\"{D}\"}}",
            })

    dispatch.register("open", cmd)
