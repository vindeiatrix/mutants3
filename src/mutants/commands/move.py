from __future__ import annotations

from typing import Any, Dict

import logging
import os

from mutants.registries.world import DELTA
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.app import trace as traceflags
import json

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"

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
    year, x, y = p.get("pos", [0, 0, 0])
    world = ctx["world_loader"](year)

    dec = ER.resolve(world, dyn, year, x, y, dir_code, actor={})

    if traceflags.get_flag("move"):
        logger = logging.getLogger(__name__)
        payload = {
            "pos": f"({x}E : {y}N)",
            "dir": dir_code.upper(),
            "passable": dec.passable,
            "desc": dec.descriptor,
            "cur": {"base": dec.cur_raw.get("base"), "gate_state": dec.cur_raw.get("gate_state")},
            "nbr": {"base": dec.nbr_raw.get("base"), "gate_state": dec.nbr_raw.get("gate_state")},
            "why": dec.reason_chain,
        }
        logger.info("MOVE/DECISION - %s", json.dumps(payload))
        sink = ctx.get("logsink")
        if sink is not None and hasattr(sink, "handle"):
            sink.handle({"ts": "", "kind": "MOVE/DECISION", "text": json.dumps(payload)})

    if not dec.passable:
        if dec.reason == "closed_gate":
            ctx["feedback_bus"].push(
                "MOVE/BLOCKED", f"The {DIR_WORD[dir_code]} gate is closed."
            )
        else:
            ctx["feedback_bus"].push("MOVE/BLOCKED", "You're blocked!")
        if WORLD_DEBUG:
            cur = dec.cur_raw or {}
            nbr = dec.nbr_raw or {}
            LOG.debug(
                "[move] blocked (%s,%s,%s) dir=%s reason=%s cur(base=%s,gs=%s) nbr(base=%s,gs=%s)",
                year,
                x,
                y,
                dir_code,
                getattr(dec, "reason", "blocked"),
                cur.get("base"),
                cur.get("gate_state"),
                nbr.get("base"),
                nbr.get("gate_state"),
            )
            ctx["feedback_bus"].push(
                "SYSTEM/DEBUG",
                f"[dev] move blocked: reason={getattr(dec,'reason','blocked')}; "
                f"cur(base={cur.get('base')},gs={cur.get('gate_state')}) "
                f"nbr(base={nbr.get('base')},gs={nbr.get('gate_state')})",
            )
        return

    dx, dy = DELTA[dir_code]
    p["pos"][1] = x + dx
    p["pos"][2] = y + dy
    # Successful movement requests a render of the new room.
    ctx["render_next"] = True
    # Do not echo success movement like "You head north." Original shows next room immediately.


def register(dispatch, ctx) -> None:
    dispatch.register("north", lambda arg: move("N", ctx))
    dispatch.alias("n", "north")
    dispatch.register("south", lambda arg: move("S", ctx))
    dispatch.alias("s", "south")
    dispatch.register("east", lambda arg: move("E", ctx))
    dispatch.alias("e", "east")
    dispatch.register("west", lambda arg: move("W", ctx))
    dispatch.alias("w", "west")
