from __future__ import annotations

from typing import Any, Mapping, Optional

from ..registries import items_catalog as catreg


def _coerce_weight(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    try:
        return max(0, int(float(str(value))))
    except (TypeError, ValueError):
        return None


def _resolve_base_weight(
    instance: Mapping[str, Any] | None, template: Mapping[str, Any] | None
) -> int:
    """Resolve the base weight for an item instance ignoring enchantments."""

    for payload in (instance, template):
        if not isinstance(payload, Mapping):
            continue
        for key in ("effective_weight", "effective_weight_lbs", "effective_lbs"):
            weight = _coerce_weight(payload.get(key))
            if weight is not None:
                return weight

    if isinstance(instance, Mapping):
        weight = _coerce_weight(instance.get("weight"))
        if weight is not None:
            return weight

    if isinstance(template, Mapping):
        for key in ("weight", "weight_lbs", "lbs"):
            weight = _coerce_weight(template.get(key))
            if weight is not None:
                return weight

    return 0


def _template_for_instance(instance: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(instance, Mapping):
        return None

    item_id = (
        instance.get("item_id")
        or instance.get("catalog_id")
        or instance.get("id")
        or instance.get("template_id")
    )
    if not item_id:
        return None

    catalog = catreg.load_catalog() or {}
    template = catalog.get(str(item_id))
    if isinstance(template, Mapping):
        return template
    return None


def get_effective_weight(
    instance: Mapping[str, Any] | None, template: Mapping[str, Any] | None = None
) -> int:
    """Return the effective carried weight for ``instance``.

    Applies enchantment-based weight reduction while enforcing the 10 lb floor
    for heavier items. Callers may provide a catalog ``template`` to avoid
    redundant lookups; otherwise the template is loaded from the catalog.
    """

    resolved_template = template if isinstance(template, Mapping) else _template_for_instance(instance)
    base_weight = _resolve_base_weight(instance, resolved_template)
    if base_weight <= 0:
        return 0

    enchant_level = 0
    if isinstance(instance, Mapping):
        try:
            enchant_level = int(instance.get("enchant_level", 0))
        except (TypeError, ValueError):
            enchant_level = 0

    if enchant_level >= 1 and base_weight > 10:
        return max(10, base_weight - (10 * enchant_level))

    return base_weight


def effective_weight(
    instance: Mapping[str, Any] | None, template: Mapping[str, Any] | None
) -> int:
    """Backward-compatible wrapper for legacy imports."""

    return get_effective_weight(instance, template)
