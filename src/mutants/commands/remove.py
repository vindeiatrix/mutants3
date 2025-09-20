from __future__ import annotations

from typing import Dict, Optional

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import item_transfer as itx
from ..services import player_state as pstate
from ..services.equip_debug import _edbg_enabled, _edbg_log
from .convert import _display_name


def _inventory_items(payload: object) -> list[str]:
    if isinstance(payload, dict):
        inventory = payload.get("inventory")
        if isinstance(inventory, list):
            return [str(item) for item in inventory if item]
    return []


def _bag_count(player: Optional[Dict[str, object]] = None, state: Optional[Dict[str, object]] = None) -> int:
    if player:
        items = _inventory_items(player)
        if items:
            return len(items)
    if state and isinstance(state, dict):
        active = state.get("active")
        if isinstance(active, dict):
            items = _inventory_items(active)
            if items:
                return len(items)
        return len(_inventory_items(state))
    return 0


def remove_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    if (arg or "").strip():
        if _edbg_enabled():
            try:
                state = pstate.load_state()
            except Exception:
                state = None
            cls_name = pstate.get_active_class(state) if state else None
            slot_iid = pstate.get_equipped_armour_id(state) if state else None
            _edbg_log(
                "[ equip ] reject=unexpected_argument",
                cmd="remove",
                **{
                    "class": cls_name or "None",
                    "bag_count": _bag_count(state=state),
                    "slot_iid": slot_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", "Usage: remove")
        return {"ok": False, "reason": "unexpected_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    try:
        stats_state = pstate.load_state()
    except Exception:
        stats_state = None
    cls_name = pstate.get_active_class(stats_state) if stats_state else None

    current = pstate.get_equipped_armour_id(player)
    current_item_id: Optional[str] = None
    if current:
        inst = itemsreg.get_instance(current) or {}
        current_item_id = (
            inst.get("item_id")
            or inst.get("catalog_id")
            or inst.get("id")
            or current
        )
    if _edbg_enabled():
        _edbg_log(
            "[ equip ] remove enter",
            cmd="remove",
            **{
                "class": cls_name or "None",
                "bag_count": _bag_count(player, stats_state),
                "slot_iid": current or "None",
                "slot_item_id": repr(str(current_item_id)) if current_item_id else "None",
            },
        )

    if not current:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=no_armour_equipped",
                cmd="remove",
                **{
                    "class": cls_name or "None",
                    "bag_count": _bag_count(player, stats_state),
                },
            )
        bus.push("SYSTEM/WARN", "You're not wearing any armour.")
        return {"ok": False, "reason": "no_armour"}

    inventory = player.get("inventory")
    bag_size = len(inventory) if isinstance(inventory, list) else 0
    if bag_size >= itx.INV_CAP:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=capacity_block_on_remove",
                cmd="remove",
                **{
                    "class": cls_name or "None",
                    "bag_count": bag_size,
                    "capacity": itx.INV_CAP,
                    "slot_iid": current,
                },
            )
        bus.push("SYSTEM/WARN", "You're to encumbered to do that!")
        return {"ok": False, "reason": "bag_full"}

    removed = pstate.unequip_armour()
    if not removed:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=internal_error",
                cmd="remove",
                **{
                    "class": cls_name or "None",
                    "slot_iid": current,
                },
            )
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
    result = {"ok": True, "iid": removed, "item_id": item_id}

    if _edbg_enabled():
        try:
            final_state = pstate.load_state()
        except Exception:
            final_state = None
        _edbg_log(
            "[ equip ] success=remove",
            cmd="remove",
            **{
                "class": cls_name or "None",
                "bag_count": _bag_count(state=final_state),
                "slot_iid": "None",
                "removed_iid": removed,
                "removed_item_id": repr(str(item_id)),
            },
        )

    return result


def register(dispatch, ctx) -> None:
    dispatch.register("remove", lambda arg: remove_cmd(arg, ctx))
    dispatch.alias("rem", "remove")
    dispatch.alias("remo", "remove")
