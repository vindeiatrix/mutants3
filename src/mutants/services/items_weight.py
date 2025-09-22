from __future__ import annotations

from typing import Any, Mapping, Optional


def _coerce_weight(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    try:
        return max(0, int(float(str(value))))
    except (TypeError, ValueError):
        return None


def effective_weight(
    instance: Mapping[str, Any] | None, template: Mapping[str, Any] | None
) -> int:
    """Return the effective weight for an item instance.

    Prefers explicit effective-weight overrides, falling back to standard weight
    metadata from the instance and catalog template.
    """

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
