from __future__ import annotations
from ..services import item_transfer as itx
from mutants.registries import items_catalog, items_instances as itemsreg
from ..ui.item_display import item_label
from ..util.textnorm import normalize_item_query
from .argcmd import ArgSpec, run_argcmd
def get_cmd(arg: str, ctx):
    spec = ArgSpec(
        verb="GET",
        arg_policy="required",
        messages={
            "usage": "Type GET [item name] to pick up an item.",
            "invalid": "There isn't a {subject} here.",
            "success": "You pick up the {name}.",
        },
        reason_messages={
            "not_found": "There isn't a {subject} here.",
            "usage": "Type GET [item name] to pick up an item.",
        },
        success_kind="LOOT/PICKUP",
        warn_kind="SYSTEM/WARN",
    )

    cat = items_catalog.load_catalog()

    def action(prefix: str):
        q = normalize_item_query(prefix)
        if not q:
            return {"ok": False, "reason": "usage"}
        dec = itx.pick_from_ground(ctx, q)
        if dec.get("ok") and dec.get("iid"):
            inst = itemsreg.get_instance(dec["iid"]) or {}
            tpl = cat.get(inst.get("item_id")) or {}
            dec["display_name"] = item_label(inst, tpl, show_charges=False)
        return dec

    run_argcmd(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("get", lambda arg: get_cmd(arg, ctx))
    dispatch.alias("take", "get")
    dispatch.alias("pickup", "get")
