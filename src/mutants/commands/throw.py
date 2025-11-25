from __future__ import annotations
from ..services import item_transfer as itx
from mutants.registries import items_catalog, items_instances as itemsreg
from ..ui.item_display import item_label
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
            "ambiguous": "Which {item}?",
            "invalid_direction": "No exit that way.",
        },
        success_kind="COMBAT/THROW",
        warn_kind="SYSTEM/WARN",
    )

    decision_holder = {}
    cat = items_catalog.load_catalog()

    def action(dir: str, item: str):
        dec = itx.throw_to_direction(ctx, dir, item)
        if dec.get("ok") and dec.get("iid"):
            inst = itemsreg.get_instance(dec["iid"]) or {}
            tpl = cat.get(inst.get("item_id")) or {}
            dec["display_name"] = item_label(inst, tpl, show_charges=False)
        decision_holder["dec"] = dec
        return dec

    run_argcmd_positional(ctx, spec, arg, action)

    dec = decision_holder.get("dec") or {}
    if dec.get("ok") and not dec.get("blocked") and dec.get("direction"):
        ctx["feedback_bus"].push(
            "COMBAT/THROW",
            f"You hear loud sounds of clashing metal to the {dec['direction']}.",
        )
    if dec.get("blocked") and dec.get("display_name"):
        ctx["feedback_bus"].push(
            "COMBAT/THROW", f"{dec['display_name']} has fallen to the ground!"
        )


def register(dispatch, ctx) -> None:
    dispatch.register("throw", lambda arg: throw_cmd(arg, ctx))
