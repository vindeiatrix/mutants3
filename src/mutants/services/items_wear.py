from __future__ import annotations

from typing import Any, Dict

from mutants.registries import items_instances


def _sanitize_wear_amount(amount: int) -> int:
    try:
        value = int(amount)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def apply_wear(iid: str, amount: int) -> Dict[str, Any]:
    """Apply *amount* of wear to the item instance ``iid``."""

    inst = items_instances.get_instance(iid)
    if inst is None:
        raise KeyError(iid)

    current_condition = items_instances.get_condition(iid)

    if items_instances.is_enchanted(iid):
        return {"cracked": False, "condition": current_condition}

    if current_condition <= 0:
        return {"cracked": False, "condition": 0}

    wear_amount = _sanitize_wear_amount(amount)
    if wear_amount <= 0:
        return {"cracked": False, "condition": current_condition}

    next_condition = max(0, current_condition - wear_amount)

    if next_condition <= 0:
        items_instances.crack_instance(iid)
        return {"cracked": True, "condition": 0}

    updated = items_instances.set_condition(iid, next_condition)
    return {"cracked": False, "condition": updated}


def wear_from_event(event: Any) -> int:
    """Derive a wear value from a combat/event payload."""

    return 5
