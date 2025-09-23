from __future__ import annotations

from typing import Any, Mapping, Optional

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _armour_class_from_payload(payload: Any) -> Optional[int]:
    if not isinstance(payload, Mapping):
        return None

    derived = payload.get("derived")
    if isinstance(derived, Mapping) and derived.get("armour_class") is not None:
        return max(0, _coerce_int(derived.get("armour_class")))

    base_value = payload.get("armour_class")
    enchant_level = payload.get("enchant_level")

    if base_value is None:
        item_id = payload.get("item_id")
        template: Optional[Mapping[str, Any]] = None
        if item_id:
            try:
                catalog = items_catalog.load_catalog()
            except FileNotFoundError:
                catalog = None
            if catalog:
                template = catalog.get(str(item_id))
        if template and template.get("armour_class") is not None:
            base_value = template.get("armour_class")

    base_ac = max(0, _coerce_int(base_value))
    enchant_bonus = max(0, _coerce_int(enchant_level))
    return base_ac + enchant_bonus


def armour_class_from_equipped(state) -> int:
    """Return the armour class bonus provided by the equipped armour."""

    if isinstance(state, Mapping):
        armour_payload = state.get("armour_slot")
        bonus = _armour_class_from_payload(armour_payload)
        if bonus is not None:
            return bonus

    armour_iid = pstate.get_equipped_armour_id(state)
    if not armour_iid:
        return 0

    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = None

    template: Optional[dict[str, Any]] = None
    inst = itemsreg.get_instance(armour_iid)
    if inst:
        tpl_id: Optional[str] = None
        for key in ("item_id", "catalog_id", "id"):
            candidate = inst.get(key)
            if candidate is None:
                continue
            tpl_id = str(candidate)
            if tpl_id:
                break
        if tpl_id and catalog:
            template = catalog.get(tpl_id)

    if not template and catalog:
        template = catalog.get(str(armour_iid))
    if not template:
        return 0

    enchant_level = itemsreg.get_enchant_level(armour_iid)
    base_ac = max(0, _coerce_int(template.get("armour_class")))
    return base_ac + max(0, enchant_level)


def dex_bonus_for_active(state) -> int:
    """Return the derived dexterity bonus for the active character."""

    if isinstance(state, Mapping):
        derived = state.get("derived")
        if isinstance(derived, Mapping) and derived.get("dex_bonus") is not None:
            return max(0, _coerce_int(derived.get("dex_bonus")))

        stats = state.get("stats")
        if isinstance(stats, Mapping) and stats.get("dex") is not None:
            try:
                dex_value = int(stats.get("dex", 0))
            except (TypeError, ValueError):
                dex_value = 0
            return max(0, dex_value // 10)

    stats = pstate.get_stats_for_active(state)
    dex = stats.get("dex", 0)
    try:
        dex_value = int(dex)
    except (TypeError, ValueError):
        dex_value = 0
    return max(0, dex_value // 10)


def armour_class_for_active(state) -> int:
    """Return the active character's armour class."""

    return dex_bonus_for_active(state) + armour_class_from_equipped(state)
