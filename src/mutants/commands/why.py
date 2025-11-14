from __future__ import annotations
from typing import Any, Dict

from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.services import player_state as pstate

DIRS = {"n", "s", "e", "w"}


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def why_cmd(arg: str, ctx) -> None:
    parts = arg.split()
    if not parts:
        ctx["feedback_bus"].push("SYSTEM/OK", "Usage: why <n|s|e|w>")
        return
    d = parts[0].lower()[0]
    if d not in DIRS:
        ctx["feedback_bus"].push("SYSTEM/WARN", "Usage: why <n|s|e|w>")
        return
    year, x, y = pstate.canonical_player_pos(ctx.get("player_state"))
    world = ctx["world_loader"](year)
    dec = ER.resolve(world, dyn, year, x, y, d, actor={})
    chain = "; ".join(f"{layer}={detail}" for (layer, detail) in dec.reason_chain)
    ctx["feedback_bus"].push(
        "SYSTEM/OK",
        f"{d.upper()}: {dec.descriptor} | passable={dec.passable} | {chain}",
    )


def register(dispatch, ctx) -> None:
    dispatch.register("why", lambda arg: why_cmd(arg, ctx))
