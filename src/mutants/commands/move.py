from __future__ import annotations

from typing import Any, Callable, Dict, List

from mutants.registries.world import (
    BASE_BOUNDARY,
    BASE_GATE,
    BASE_TERRAIN,
    DELTA,
    GATE_CLOSED,
    GATE_LOCKED,
)
from mutants.ui.viewmodels import RoomVM


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def register(dispatch: Dict[str, Callable[[str], None]], ctx: Dict[str, Any]) -> None:
    """Register movement and look commands on *dispatch* using *ctx*."""

    def bind(cmds: List[str], dir_code: str) -> None:
        def cmd(_arg: str) -> None:
            move(dir_code, ctx)

        for c in cmds:
            dispatch[c] = cmd

    bind(["north", "n"], "N")
    bind(["south", "s"], "S")
    bind(["east", "e"], "E")
    bind(["west", "w"], "W")

    dispatch["look"] = lambda _arg: look_current(ctx)


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
        print(msg)
        look_current(ctx)
        return

    dx, dy = DELTA[dir_code]
    p["pos"][1] = x + dx
    p["pos"][2] = y + dy
    look_current(ctx)


def look_current(ctx: Dict[str, Any]) -> None:
    """Render the current room for the active player."""
    vm = build_room_vm(ctx)
    lines = ctx["render"](vm)
    for line in lines:
        print(line)


def build_room_vm(ctx: Dict[str, Any]) -> RoomVM:
    state = ctx["player_state"]
    p = _active(state)
    year, x, y = p.get("pos", [2000, 0, 0])
    world = ctx["world_loader"](year)
    tile = world.get_tile(x, y)

    headers = ctx.get("headers", [])
    idx = int(tile.get("header_idx", 0)) if tile else 0
    header = headers[idx] if 0 <= idx < len(headers) else ""

    dirs = {}
    if tile:
        for d in ("N", "S", "E", "W"):
            e = tile["edges"].get(d, {})
            dirs[d] = {k: e.get(k) for k in ("base", "gate_state", "key_type")}

    monsters_here: List[Dict[str, str]] = []
    mon_reg = ctx.get("monsters")
    if mon_reg:
        try:
            for m in mon_reg.list_at(year, x, y):  # type: ignore[attr-defined]
                name = m.get("name") or m.get("monster_id", "?")
                monsters_here.append({"name": name})
        except Exception:
            pass

    ground_items: List[Dict[str, str]] = []
    items_reg = ctx.get("items")
    if items_reg and hasattr(items_reg, "list_at"):
        try:
            for it in items_reg.list_at(year, x, y):  # type: ignore[attr-defined]
                name = it.get("name") or it.get("item_id", "?")
                ground_items.append({"name": name})
        except Exception:
            pass

    vm: RoomVM = {
        "header": header,
        "coords": {"x": x, "y": y},
        "dirs": dirs,
        "monsters_here": monsters_here,
        "ground_items": ground_items,
        "events": [],
        "shadows": [],
        "flags": {"dark": bool(tile.get("dark")) if tile else False},
    }
    return vm
