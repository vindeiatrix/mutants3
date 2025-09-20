"""Helpers for basic economy calculations.

These helpers intentionally keep the logic simple so they can be swapped out
later when a full shop/economy system is implemented.  Both functions rely on
the item catalog for the base ``riblet_value`` of an item instance and only
use local state that can be fetched directly from the registries.
"""

from __future__ import annotations

from typing import Dict, Optional

from mutants.registries import items_catalog, items_instances as itemsreg

# Enchantments increase value by 25% per level.  This keeps prices monotonic
# while leaving plenty of room to tune once shops exist.
_ENCHANT_STEP_PERCENT = 25

# Repairs charge 5% of the base riblet value for every condition point restored.
_REPAIR_FACTOR_NUMERATOR = 5
_REPAIR_FACTOR_DENOMINATOR = 100


def _coerce_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _base_value_from_template(template: Optional[Dict[str, object]]) -> int:
    if not isinstance(template, dict):
        return 0
    raw = _coerce_int(template.get("riblet_value"))
    return max(0, raw)


def _scale_by_percent(amount: int, percent: int) -> int:
    if amount <= 0 or percent <= 0:
        return 0
    return (amount * percent) // 100


def _enchant_percent(level: int) -> int:
    return 100 + max(0, level) * _ENCHANT_STEP_PERCENT


def _condition_percent(condition: int) -> int:
    if condition <= 0:
        return 0
    return min(condition, 100)


def sell_price_for(iid: str) -> int:
    """Return the riblet sell price for the instance ``iid``.

    The calculation uses the item's catalog ``riblet_value`` scaled by the
    enchantment multiplier.  Non-enchanted items are additionally scaled by the
    current condition so damaged items sell for less.
    """

    inst = itemsreg.get_instance(iid)
    if not inst:
        return 0

    catalog = items_catalog.load_catalog()
    item_id = inst.get("item_id") if isinstance(inst, dict) else None
    template = catalog.get(item_id) if item_id else None
    base_value = _base_value_from_template(template)
    if base_value <= 0:
        return 0

    enchant_level = itemsreg.get_enchant_level(iid)
    price = _scale_by_percent(base_value, _enchant_percent(enchant_level))

    if enchant_level == 0:
        condition = itemsreg.get_condition(iid)
        price = _scale_by_percent(price, _condition_percent(condition))

    return max(0, int(price))


def repair_cost_for(iid: str, target_condition: int) -> int:
    """Return the riblet cost to repair ``iid`` up to ``target_condition``.

    ``target_condition`` is clamped between the current condition and 100.  The
    total cost grows with both the number of condition points restored and the
    catalog's base ``riblet_value``.  Costs are derived from a placeholder
    factor of 5% of the base value per condition point.
    """

    inst = itemsreg.get_instance(iid)
    if not inst:
        return 0

    catalog = items_catalog.load_catalog()
    item_id = inst.get("item_id") if isinstance(inst, dict) else None
    template = catalog.get(item_id) if item_id else None
    base_value = _base_value_from_template(template)
    if base_value <= 0:
        return 0

    current_condition = itemsreg.get_condition(iid)
    target = max(current_condition, min(_coerce_int(target_condition), 100))
    points = max(0, target - current_condition)
    if points <= 0:
        return 0

    scaled = points * base_value * _REPAIR_FACTOR_NUMERATOR
    scaled += _REPAIR_FACTOR_DENOMINATOR - 1
    cost = scaled // _REPAIR_FACTOR_DENOMINATOR
    return max(0, int(cost))

