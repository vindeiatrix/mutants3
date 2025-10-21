from __future__ import annotations

from collections.abc import Mapping
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


WEAR_EVENT_KIND = "weapon-hit"
WEAR_PER_HIT = 5


def build_wear_event(*, actor: str, source: str, damage: Any) -> Dict[str, Any]:
    """Return a normalized wear event payload for downstream consumers."""

    try:
        sanitized_damage = int(damage)
    except (TypeError, ValueError):
        sanitized_damage = 0
    payload: Dict[str, Any] = {
        "kind": WEAR_EVENT_KIND,
        "actor": str(actor or "") or "unknown",
        "source": str(source or "") or "unknown",
        "damage": max(0, sanitized_damage),
    }
    return payload


def wear_from_event(event: Any) -> int:
    """Derive a wear value from a combat/event payload."""

    if not isinstance(event, Mapping):
        return 0
    try:
        damage = int(event.get("damage", 0))
    except (TypeError, ValueError):
        return 0
    if damage <= 0:
        return 0
    return WEAR_PER_HIT
