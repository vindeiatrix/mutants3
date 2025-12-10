from __future__ import annotations
from .argcmd import coerce_direction
from ._util.items import resolve_item_arg
from ..registries import items_catalog, items_instances as itemsreg
from ..services import combat_actions, items_ranged


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
    iid = resolve_item_arg(ctx, item_token)
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
    bus.push("COMBAT/HIT", f"You release the {name} {d.lower()}!")

    try:
        combat_actions.perform_ranged_attack(ctx=ctx, direction=d, weapon_iid=iid)
    except Exception:
        # Defensive: keep feedback consistent with existing behavior even if combat fails.
        bus.push("SYSTEM/WARN", "Your bolt fizzles out.")


def register(dispatch, ctx) -> None:
    dispatch.register("point", lambda arg: point_cmd(arg, ctx))
