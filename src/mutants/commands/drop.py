from __future__ import annotations
from ..services import item_transfer as itx
from ..ui import item_display as idisp
from .argcmd import ArgSpec, run_argcmd
def drop_cmd(arg: str, ctx):
    spec = ArgSpec(
        verb="DROP",
        arg_policy="required",
        messages={
            "usage": "Type DROP [item name] to drop an item.",
            "invalid": "You're not carrying a {subject}.",
            "success": "You drop the {name}.",
        },
        reason_messages={
            "inventory_empty": "You have nothing to drop.",
            "armor_cannot_drop": "You can't drop what you're wearing.",
        },
        success_kind="LOOT/DROP",
        warn_kind="SYSTEM/WARN",
    )

    def action(prefix: str):
        dec = itx.drop_to_ground(ctx, prefix)
        if dec.get("ok") and dec.get("iid"):
            dec["display_name"] = idisp.canonical_name_from_iid(dec["iid"])
        return dec

    run_argcmd(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("drop", lambda arg: drop_cmd(arg, ctx))
    dispatch.alias("put", "drop")
