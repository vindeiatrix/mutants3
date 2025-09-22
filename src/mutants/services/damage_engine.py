"""Utilities for resolving combat damage."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_calc, player_state as pstate


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion of ``value`` to ``int`` with ``default`` fallback."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_mapping(payload: Any) -> MutableMapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _resolve_instance_id(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("iid", "instance_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _resolve_item_id(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("item_id", "catalog_id", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _resolve_base_power(payload: Mapping[str, Any]) -> int:
    if not payload:
        return 0

    if "base_power" in payload:
        return max(0, _coerce_int(payload.get("base_power"), 0))

    if "power_base" in payload:
        return max(0, _coerce_int(payload.get("power_base"), 0))

    item_id = _resolve_item_id(payload)
    if not item_id:
        return 0

    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        return 0

    template = catalog.get(item_id)
    if not isinstance(template, Mapping):
        return 0

    return max(0, _coerce_int(template.get("base_power"), 0))


def _resolve_enchant_level(item: Any, payload: Mapping[str, Any]) -> int:
    if "enchant_level" in payload:
        return max(0, _coerce_int(payload.get("enchant_level"), 0))

    instance_id = _resolve_instance_id(payload)
    if instance_id:
        return max(0, itemsreg.get_enchant_level(instance_id))

    if isinstance(item, str) and item:
        return max(0, itemsreg.get_enchant_level(item))

    return 0


def get_total_ac(defender_state: Any) -> int:
    """Return the defender's total armour class."""

    ac = combat_calc.armour_class_for_active(defender_state)
    return max(0, _coerce_int(ac, 0))


def _resolve_item_payload(item: Any) -> MutableMapping[str, Any]:
    if isinstance(item, str) and item:
        inst = itemsreg.get_instance(item)
        if isinstance(inst, Mapping):
            return dict(inst)
        return {"item_id": item}
    return _normalize_mapping(item)


def _resolve_attacker_strength(attacker_state: Any) -> int:
    stats = pstate.get_stats_for_active(attacker_state)
    strength = _coerce_int(stats.get("str"), 0)
    return max(0, strength // 10)


def get_attacker_power(item: Any, attacker_state: Any) -> int:
    """Return the attacker's raw power before mitigation."""

    payload = _resolve_item_payload(item)
    base_power = _resolve_base_power(payload)
    enchant_level = _resolve_enchant_level(item, payload)
    strength_bonus = _resolve_attacker_strength(attacker_state)

    return base_power + (4 * enchant_level) + strength_bonus


def compute_base_damage(item: Any, attacker_state: Any, defender_state: Any) -> int:
    """Return the base damage before applying the AC mitigation curve."""

    attack_power = get_attacker_power(item, attacker_state)
    defender_ac = get_total_ac(defender_state)
    return attack_power - defender_ac

