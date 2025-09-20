from __future__ import annotations

from typing import Any, Optional

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def armour_class_from_equipped(state) -> int:
    """Return the armour class bonus provided by the equipped armour."""

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

    return max(0, _coerce_int(template.get("armour_class")))


def dex_bonus_for_active(state) -> int:
    """Return the derived dexterity bonus for the active character."""

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
