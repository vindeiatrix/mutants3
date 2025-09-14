from __future__ import annotations
from ..services import item_transfer as itx
from ..ui import item_display as idisp
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

    def action(prefix: str):
        q = normalize_item_query(prefix)
        if not q:
            return {"ok": False, "reason": "usage"}
        dec = itx.pick_from_ground(ctx, q)
        if dec.get("ok") and dec.get("iid"):
            dec["display_name"] = idisp.canonical_name_from_iid(dec["iid"])
        return dec

    run_argcmd(ctx, spec, arg, action)


def register(dispatch, ctx) -> None:
    dispatch.register("get", lambda arg: get_cmd(arg, ctx))
    dispatch.alias("take", "get")
    dispatch.alias("pickup", "get")
