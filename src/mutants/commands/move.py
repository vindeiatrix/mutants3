from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping

import logging
import os

from mutants.registries.world import DELTA
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.services import player_state as pstate
from mutants.app import trace as traceflags
import json

from mutants.services import state_debug

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"

DIR_WORD = {"N": "north", "S": "south", "E": "east", "W": "west"}


def move(dir_code: str, ctx: Dict[str, Any]) -> None:
    """Attempt to move the active player in direction *dir_code*."""
    state = ctx.get("player_state")
    year, x, y = pstate.canonical_player_pos(state)
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
    canonical_state: MutableMapping[str, Any]
    if isinstance(state, MutableMapping):
        canonical_state = state
    elif isinstance(state, Mapping):
        canonical_state = dict(state)
    else:
        canonical_state = {}

    try:
        ions_before = pstate.get_ions_for_active(canonical_state)
    except Exception:
        ions_before = None

    new_pos = pstate.move_player(
        canonical_state, pstate.get_active_class(canonical_state), (0, dx, dy)
    )

    save_success = False
    try:
        save_success = pstate.save_state(canonical_state, reason="autosave:move")
    except Exception:
        LOG.exception("Failed to autosave position after move.")
    else:
        if save_success:
            # Preserve the ready target across movement; it should only be cleared
            # when explicitly reset (e.g. on death or exit).
            pass

    refreshed: Mapping[str, Any] | None = None
    ions_after = ions_before
    if save_success:
        try:
            refreshed = pstate.load_state()
        except Exception:
            refreshed = None
    if refreshed is None:
        refreshed = canonical_state
    if isinstance(refreshed, Mapping) and not isinstance(refreshed, dict):
        refreshed = dict(refreshed)
    if isinstance(refreshed, dict):
        pstate.normalize_player_state_inplace(refreshed)
        ctx["player_state"] = refreshed

    pstate.sync_runtime_position(ctx, new_pos)
    try:
        ions_after = pstate.get_ions_for_active(refreshed) if isinstance(refreshed, Mapping) else ions_before
    except Exception:
        ions_after = ions_before
    state_debug.log_travel(
        ctx,
        command="move",
        arg=dir_code,
        from_pos=[year, x, y],
        to_pos=new_pos,
        ions_before=ions_before,
        ions_after=ions_after,
    )
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
