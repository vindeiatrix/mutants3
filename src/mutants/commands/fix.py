from __future__ import annotations
from ._helpers import find_inventory_item_by_prefix
from ..registries import items_catalog, items_instances as itemsreg


def fix_cmd(arg: str, ctx):
    tok = (arg or "").strip()
    bus = ctx["feedback_bus"]
    if not tok:
        bus.push("SYSTEM/WARN", "Usage: fix [item]")
        return
    iid = find_inventory_item_by_prefix(ctx, tok)
    if not iid:
        bus.push("SYSTEM/WARN", f"You're not carrying a {tok}.")
        return
    inst = itemsreg.get_instance(iid) or {}
    cat = items_catalog.load_catalog()
    tpl = cat.get(inst.get("item_id")) or {}
    name = tpl.get("name") or inst.get("item_id") or tok
    if not tpl.get("charges_max"):
        bus.push("SYSTEM/WARN", "That doesn't need fixing.")
        return
    gain = itemsreg.recharge_full(iid)
    if gain <= 0:
        bus.push("SYSTEM/OK", "It's already at full charge.")
    else:
        bus.push("SYSTEM/OK", f"You restore the {name} to full charge.")


def register(dispatch, ctx) -> None:
    dispatch.register("fix", lambda arg: fix_cmd(arg, ctx))
