from __future__ import annotations

from typing import Dict

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import item_transfer as itx
from ..services import player_state as pstate
from .convert import _display_name


def remove_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    if (arg or "").strip():
        bus.push("SYSTEM/WARN", "Usage: remove")
        return {"ok": False, "reason": "unexpected_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    current = pstate.get_equipped_armour_id(player)
    if not current:
        bus.push("SYSTEM/WARN", "You're not wearing any armour.")
        return {"ok": False, "reason": "no_armour"}

    inventory = player.get("inventory")
    bag_size = len(inventory) if isinstance(inventory, list) else 0
    if bag_size >= itx.INV_CAP:
        bus.push("SYSTEM/WARN", "You're to encumbered to do that!")
        return {"ok": False, "reason": "bag_full"}

    removed = pstate.unequip_armour()
    if not removed:
        bus.push("SYSTEM/WARN", "Nothing happens.")
        return {"ok": False, "reason": "unequip_failed"}

    inst = itemsreg.get_instance(removed) or {}
    item_id = (
        inst.get("item_id")
        or inst.get("catalog_id")
        or inst.get("id")
        or removed
    )
    name = _display_name(str(item_id), catalog)

    bus.push("SYSTEM/OK", f"You remove the {name}.")
    return {"ok": True, "iid": removed, "item_id": item_id}


def register(dispatch, ctx) -> None:
    dispatch.register("remove", lambda arg: remove_cmd(arg, ctx))
    dispatch.alias("rem", "remove")
    dispatch.alias("remo", "remove")
