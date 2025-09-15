from __future__ import annotations
from ..services import item_transfer as itx
from mutants.registries import items_catalog, items_instances as itemsreg
from ..ui.item_display import item_label
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

    cat = items_catalog.load_catalog()

    def action(prefix: str):
        dec = itx.drop_to_ground(ctx, prefix)
        if dec.get("ok") and dec.get("iid"):
            inst = itemsreg.get_instance(dec["iid"]) or {}
            tpl = cat.get(inst.get("item_id")) or {}
            dec["display_name"] = item_label(inst, tpl, show_charges=False)
        return dec

    run_argcmd(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("drop", lambda arg: drop_cmd(arg, ctx))
    dispatch.alias("put", "drop")
