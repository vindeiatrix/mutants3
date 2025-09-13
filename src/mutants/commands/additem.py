from __future__ import annotations
from mutants.app import context as appctx
from mutants.registries import items_instances as itemsreg
from mutants.registries import items as items_registry
import os, logging

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"


def _pos_from_ctx() -> tuple[int, int, int]:
    ctx = appctx.current_context() if hasattr(appctx, "current_context") else None
    if not ctx:
        return 0, 0, 0
    state = ctx.get("player_state", {})
    aid = state.get("active_id")
    for pl in state.get("players", []):
        if pl.get("id") == aid:
            pos = pl.get("pos") or [0, 0, 0]
            return int(pos[0]), int(pos[1]), int(pos[2])
    pos = state.get("players", [{}])[0].get("pos") or [0, 0, 0]
    return int(pos[0]), int(pos[1]), int(pos[2])


def handle(tokens, bus):
    # Expected usage: ADD <item_name_or_id> [count]
    if len(tokens) < 2:
        bus.push("SYSTEM/INFO", "Usage: ADD <item> [count]")
        return
    item_token = tokens[1]
    count = 1
    if len(tokens) >= 3:
        try:
            count = max(1, min(99, int(tokens[2])))
        except ValueError:
            pass

    # New: resolve token against catalog; reject unknowns/gibberish.
    resolved, suggestions = items_registry.resolve_item(item_token)
    if not resolved:
        hint = ""
        if suggestions:
            hint = " Try: " + ", ".join(suggestions[:5])
        bus.push("SYSTEM/WARN", f"Unknown item '{item_token}'.{hint}")
        if WORLD_DEBUG:
            LOG.debug("[additem] reject token=%r suggestions=%r", item_token, suggestions)
        return

    # Choose canonical id to spawn (prefer catalog 'id')
    item_id = resolved.get("id") or resolved.get("name")

    # proceed with existing placement logic using item_id and count...
    year, x, y = _pos_from_ctx()
    for _ in range(count):
        itemsreg.create_and_save_instance(item_id, year, x, y, origin="debug_add")
    bus.push("DEBUG", f"added {count} x {item_id} at ({x},{y}).")


def add_cmd(arg: str, ctx) -> None:
    tokens = ["add"] + arg.strip().split()
    bus = ctx.get("feedback_bus") if isinstance(ctx, dict) else None
    if bus is None:
        bus = type("Bus", (), {"push": lambda *a, **k: None})()
    handle(tokens, bus)


def register(dispatch, ctx) -> None:
    dispatch.register("add", lambda arg: add_cmd(arg, ctx))
