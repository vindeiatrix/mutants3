"""Helpers for reading the active player's live state."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


def _coerce_mapping(value: Any) -> MutableMapping[str, Any] | dict[str, Any]:
    if isinstance(value, MutableMapping):
        return value
    if isinstance(value, Mapping):  # type: ignore[return-value]
        return dict(value)
    return {}


def get_active_player(ctx: Mapping[str, Any] | None) -> MutableMapping[str, Any]:
    """Return the active player's mutable state dictionary.

    The state manager is treated as the single source of truth.  Callers should
    always use this helper instead of caching player state at import time so
    that class switches pick up the latest inventory/position.
    """

    if not ctx:
        return {}
    state_mgr = ctx.get("state_manager") if isinstance(ctx, Mapping) else None
    if state_mgr is None:
        return {}
    try:
        active = state_mgr.get_active()
    except Exception:
        return {}
    if active is None:
        return {}
    if hasattr(active, "to_dict"):
        try:
            data = active.to_dict()
        except Exception:
            data = None
        if isinstance(data, MutableMapping):
            return data
        if isinstance(data, Mapping):
            return _coerce_mapping(data)
        if hasattr(active, "data"):
            maybe_data = getattr(active, "data")
            if isinstance(maybe_data, MutableMapping):
                return maybe_data
            if isinstance(maybe_data, Mapping):
                return _coerce_mapping(maybe_data)
    if isinstance(active, MutableMapping):
        return active
    if isinstance(active, Mapping):
        return _coerce_mapping(active)
    data_attr = getattr(active, "data", None)
    if isinstance(data_attr, MutableMapping):
        return data_attr
    if isinstance(data_attr, Mapping):
        return _coerce_mapping(data_attr)
    return {}
