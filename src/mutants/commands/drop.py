from __future__ import annotations
from ..services import item_transfer as itx


def drop_cmd(arg: str, ctx):
    prefix = arg.strip()
    dec = itx.drop_to_ground(ctx, prefix)
    if not dec.get("ok"):
        reason = dec.get("reason")
        bus = ctx["feedback_bus"]
        if reason == "inventory_empty":
            bus.push("SYSTEM/WARN", "You have nothing to drop.")
        elif reason == "armor_cannot_drop":
            bus.push("SYSTEM/WARN", "You can't drop what you're wearing.")
        elif reason == "not_found":
            bus.push("SYSTEM/WARN", "You don't have that.")
        else:
            bus.push("SYSTEM/WARN", "Nothing happens.")


def register(dispatch, ctx) -> None:
    dispatch.register("drop", lambda arg: drop_cmd(arg, ctx))
    dispatch.alias("put", "drop")
