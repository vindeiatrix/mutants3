from __future__ import annotations
from ..services import item_transfer as itx
from ..ui import item_display as idisp
from .argcmd import PosArg, PosArgSpec, run_argcmd_positional

def throw_cmd(arg: str, ctx):
    spec = PosArgSpec(
        verb="THROW",
        args=[PosArg("dir", "direction"), PosArg("item", "item_in_inventory")],
        messages={
            "usage": "Type THROW [direction] [item].",
            "invalid": "You're not carrying a {item}.",
            "success": "You throw the {name} {dir}.",
        },
        reason_messages={
            "inventory_empty": "You have nothing to throw.",
            "armor_cannot_drop": "You can't throw what you're wearing.",
            "not_found": "You're not carrying a {item}.",
        },
        success_kind="COMBAT/THROW",
        warn_kind="SYSTEM/WARN",
    )

    def action(dir: str, item: str):
        dec = itx.throw_to_direction(ctx, dir, item)
        if dec.get("ok") and dec.get("iid"):
            dec["display_name"] = idisp.canonical_name_from_iid(dec["iid"])
        return dec

    run_argcmd_positional(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("throw", lambda arg: throw_cmd(arg, ctx))
