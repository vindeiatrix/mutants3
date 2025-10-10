from __future__ import annotations
from .argcmd import coerce_direction
from ._helpers import find_inventory_item_by_prefix
from ..registries import items_catalog, items_instances as itemsreg
from ..services import items_ranged


def point_cmd(arg: str, ctx):
    bus = ctx["feedback_bus"]
    parts = (arg or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        bus.push("SYSTEM/WARN", "Usage: point [direction] [item]")
        return
    dir_token, item_token = parts[0], parts[1]
    d = coerce_direction(dir_token)
    if not d:
        bus.push("SYSTEM/WARN", "Try north, south, east, or west.")
        return
    iid = find_inventory_item_by_prefix(ctx, item_token)
    if not iid:
        bus.push("SYSTEM/WARN", f"You're not carrying a {item_token}.")
        return
    inst = itemsreg.get_instance(iid) or {}
    cat = items_catalog.load_catalog()
    tpl = cat.get(inst.get("item_id")) or {}
    name = tpl.get("name") or inst.get("item_id") or item_token
    if not tpl.get("charges_max"):
        bus.push("SYSTEM/WARN", "That item can't be fired.")
        return
    charges = items_ranged.charges_for_instance(inst)
    if charges <= 0:
        bus.push("SYSTEM/WARN", "It’s drained.")
        return

    items_ranged.consume_charge(iid, charges=charges)
    bus.push("COMBAT/POINT", f"You fire the {name} to the {d.title()}.")


def register(dispatch, ctx) -> None:
    dispatch.register("point", lambda arg: point_cmd(arg, ctx))
