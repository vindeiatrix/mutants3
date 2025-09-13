from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.registries.world import DELTA
from mutants.app.context import build_room_vm

DIR_MAP = {
    "north": "N",
    "n": "N",
    "south": "S",
    "s": "S",
    "east": "E",
    "e": "E",
    "west": "W",
    "w": "W",
}


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def look_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    arg = (arg or "").strip().lower()
    if not arg:
        ctx["render_next"] = True
        return

    dir_code = DIR_MAP.get(arg)
    if not dir_code:
        ctx["feedback_bus"].push("LOOK/BAD_DIR", "Try north, south, east, or west.")
        return

    p = _active(ctx["player_state"])
    year, x, y = p.get("pos", [0, 0, 0])
    world = ctx["world_loader"](year)
    dec = ER.resolve(world, dyn, year, x, y, dir_code, actor={})
    if not dec.passable:
        ctx["feedback_bus"].push("LOOK/BLOCKED", "You're blocked!")
        return

    dx, dy = DELTA[dir_code]
    peek_state = deepcopy(ctx["player_state"])
    p2 = _active(peek_state)
    p2["pos"][1] = x + dx
    p2["pos"][2] = y + dy
    vm = build_room_vm(
        peek_state,
        ctx["world_loader"],
        ctx["headers"],
        ctx.get("monsters"),
        ctx.get("items"),
    )
    ctx["peek_vm"] = vm
    ctx["render_next"] = True


def register(dispatch, ctx) -> None:
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
