from __future__ import annotations

from typing import Any, Dict

from mutants.registries.world import BASE_GATE

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

    def cmd(arg: str) -> None:
        token = (arg or "").strip().split()
        if not token:
            bus.push("SYSTEM/INFO", "Type CLOSE [direction] to close a gate.")
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
            bus.push("SYSTEM/WARN", "There is no gate to close that way.")
            return

        if gs in (1, 2):
            bus.push("SYSTEM/INFO", f"The {dir_full} gate is already closed.")
            return

        world.set_edge(x, y, D, gate_state=1, force_gate_base=True)
        world.save()

        bus.push("SYSTEM/OK", f"You've just closed the {dir_full} gate.")
        if logsink:
            logsink.handle({
                "ts": "",
                "kind": "GATE/CLOSE",
                "text": f"{{\"pos\":\"({x}E : {y}N)\",\"dir\":\"{D}\"}}",
            })

    dispatch.register("close", cmd)
