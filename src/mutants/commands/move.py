from __future__ import annotations

from typing import Any, Dict

from mutants.registries.world import (
    BASE_BOUNDARY,
    BASE_GATE,
    BASE_TERRAIN,
    DELTA,
    GATE_CLOSED,
    GATE_LOCKED,
)

DIR_WORD = {"N": "north", "S": "south", "E": "east", "W": "west"}


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def move(dir_code: str, ctx: Dict[str, Any]) -> None:
    """Attempt to move the active player in direction *dir_code*."""
    p = _active(ctx["player_state"])
    year, x, y = p.get("pos", [2000, 0, 0])
    world = ctx["world_loader"](year)
    tile = world.get_tile(x, y)
    if not tile:
        return

    edge = tile["edges"].get(dir_code, {"base": 0, "gate_state": 0})
    base = edge.get("base", 0)
    gate_state = edge.get("gate_state", 0)

    msg = None
    if base == BASE_BOUNDARY:
        msg = "A boundary blocks your way."
    elif base == BASE_TERRAIN:
        msg = "Terrain blocks your way."
    elif base == BASE_GATE:
        if gate_state == GATE_CLOSED:
            msg = "The gate is closed."
        elif gate_state == GATE_LOCKED:
            msg = "The gate is locked."

    if msg:
        ctx["feedback_bus"].push("MOVE/BLOCKED", msg)
        return

    dx, dy = DELTA[dir_code]
    p["pos"][1] = x + dx
    p["pos"][2] = y + dy
    ctx["feedback_bus"].push("MOVE/OK", f"You head {DIR_WORD[dir_code]}.")


def register(dispatch, ctx) -> None:
    dispatch.register("north", lambda arg: move("N", ctx))
    dispatch.alias("n", "north")
    dispatch.register("south", lambda arg: move("S", ctx))
    dispatch.alias("s", "south")
    dispatch.register("east", lambda arg: move("E", ctx))
    dispatch.alias("e", "east")
    dispatch.register("west", lambda arg: move("W", ctx))
    dispatch.alias("w", "west")
