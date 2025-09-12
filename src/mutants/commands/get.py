from __future__ import annotations
from ..services import item_transfer as itx


def get_cmd(arg: str, ctx):
    prefix = arg.strip()
    dec = itx.pick_from_ground(ctx, prefix)
    if not dec.get("ok"):
        reason = dec.get("reason")
        bus = ctx["feedback_bus"]
        if reason == "not_found":
            bus.push("SYSTEM/WARN", "You don't see that here.")
        else:
            bus.push("SYSTEM/WARN", "Nothing happens.")
    # Success -> silent


def register(dispatch, ctx) -> None:
    dispatch.register("get", lambda arg: get_cmd(arg, ctx))
    dispatch.alias("take", "get")
    dispatch.alias("pickup", "get")
