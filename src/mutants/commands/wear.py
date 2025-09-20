from __future__ import annotations

from typing import Dict, Optional, Tuple

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import player_state as pstate
from ..services import item_transfer as itx
from .convert import _choose_inventory_item, _display_name


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _resolve_candidate(
    player: Dict[str, object],
    prefix: str,
    catalog: Dict[str, Dict[str, object]],
) -> Tuple[Optional[str], Optional[str]]:
    iid, item_id = _choose_inventory_item(player, prefix, catalog)
    if not iid or not item_id:
        return None, None

    inst = itemsreg.get_instance(iid) or {}
    candidate_item = (
        inst.get("item_id")
        or inst.get("catalog_id")
        or inst.get("id")
        or item_id
    )
    return str(iid), str(candidate_item)


def _is_armour(item_id: str, catalog: Dict[str, Dict[str, object]]) -> bool:
    if item_id == itemsreg.BROKEN_ARMOUR_ID:
        return True
    template = catalog.get(item_id)
    if not isinstance(template, dict):
        return False
    return bool(template.get("armour"))


def _armour_weight(item_id: str, catalog: Dict[str, Dict[str, object]]) -> int:
    template = catalog.get(item_id)
    if not isinstance(template, dict):
        return 0
    return max(0, _coerce_int(template.get("weight"), 0))


def wear_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    prefix = (arg or "").strip()
    if not prefix:
        bus.push("SYSTEM/WARN", "Usage: wear <item>")
        return {"ok": False, "reason": "missing_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    iid, item_id = _resolve_candidate(player, prefix, catalog)
    if not iid or not item_id:
        bus.push("SYSTEM/WARN", f"You're not carrying a {prefix}.")
        return {"ok": False, "reason": "not_found"}

    if not _is_armour(item_id, catalog):
        bus.push("SYSTEM/WARN", "You can't wear that.")
        return {"ok": False, "reason": "not_armour"}

    stats_state = pstate.load_state()
    stats = pstate.get_stats_for_active(stats_state)
    strength = _coerce_int(stats.get("str"), 0)
    weight = _armour_weight(item_id, catalog)
    if strength < weight:
        bus.push("SYSTEM/WARN", "You don't have the strength to put that on!")
        return {"ok": False, "reason": "insufficient_strength"}

    current = pstate.get_equipped_armour_id(stats_state)
    current_name: Optional[str] = None
    if current:
        current_inst = itemsreg.get_instance(current) or {}
        current_item_id = (
            current_inst.get("item_id")
            or current_inst.get("catalog_id")
            or current_inst.get("id")
            or current
        )
        current_name = _display_name(str(current_item_id), catalog)

    try:
        if current:
            pstate.unequip_armour()
        equipped = pstate.equip_armour(iid)
    except ValueError:
        bus.push("SYSTEM/WARN", "You can't wear that.")
        return {"ok": False, "reason": "equip_failed"}

    name = _display_name(item_id, catalog)
    if current and current_name:
        bus.push("SYSTEM/OK", f"You've removed the {current_name}.")
    bus.push("SYSTEM/OK", f"You've just put on the {name}.")

    result: Dict[str, object] = {"ok": True, "iid": equipped, "item_id": item_id}
    if current:
        result["swapped"] = current
    return result


def register(dispatch, ctx) -> None:
    dispatch.register("wear", lambda arg: wear_cmd(arg, ctx))
    dispatch.alias("wea", "wear")
