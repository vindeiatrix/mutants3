from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.registries.world import DELTA
from mutants.app.context import build_room_vm
from .argcmd import coerce_direction
from ._helpers import find_inventory_item_by_prefix
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.ui.item_display import describe_instance
from mutants.services import player_state as pstate

DIR_CODE = {"north": "N", "south": "S", "east": "E", "west": "W"}


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def look_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    token = (arg or "").strip()
    if not token:
        # Explicit room refresh should always show current monsters.
        ctx["_force_show_monsters"] = True
        ctx["render_next"] = True
        return

    # Prefer inventory lookup first so ambiguous prefixes like "n" hit items before directions.
    iid = find_inventory_item_by_prefix(ctx, token)
    if iid:
        inst = itemsreg.get_instance(iid) or {}
        cat = items_catalog.load_catalog()
        tpl = cat.get(inst.get("item_id")) or {}
        desc = describe_instance(iid)
        if tpl.get("uses_charges") or tpl.get("charges_max") is not None:
            ch = int(inst.get("charges", 0))
            desc = f"{desc}  Charges: {ch}."
        ctx["feedback_bus"].push("SYSTEM/OK", desc)
        return

    dir_full = coerce_direction(token)
    if dir_full:
        dir_code = DIR_CODE[dir_full]
        year, x, y = pstate.canonical_player_pos(ctx.get("player_state"))
        world = ctx["world_loader"](year)
        dec = ER.resolve(world, dyn, year, x, y, dir_code, actor={})
        if not dec.passable:
            ctx["feedback_bus"].push("LOOK/BLOCKED", "You're blocked!")
            return
        dx, dy = DELTA[dir_code]
        peek_state = deepcopy(ctx["player_state"])
        p2 = _active(peek_state)
        p2_pos = list(p2.get("pos") or [year, x, y])
        if len(p2_pos) < 3:
            p2_pos = [year, x, y]
        p2_pos[0] = year
        p2_pos[1] = x + dx
        p2_pos[2] = y + dy
        p2["pos"] = p2_pos
        vm = build_room_vm(
            peek_state,
            ctx["world_loader"],
            ctx["headers"],
            ctx.get("monsters"),
            ctx.get("items"),
        )
        # Suppress shadow cues for adjacent peeks; shadows are only shown for the current tile.
        vm = dict(vm)
        vm["shadows"] = []
        ctx["_suppress_shadows_once"] = False
        ctx["_shadow_hint_once"] = []
        ctx["peek_vm"] = vm
        ctx["render_next"] = True
        return

    ctx["feedback_bus"].push("LOOK/BAD_DIR", "Try north, south, east, or west.")


def register(dispatch, ctx) -> None:
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
