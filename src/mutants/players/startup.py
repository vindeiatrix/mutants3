"""Utilities for granting starting currency to player profiles."""

from __future__ import annotations

from typing import Any, MutableMapping, Mapping

START_IONS: dict[str, int] = {
    "fresh": 30_000,
    "buried": 30_000,
    "resurrected": 15_000,
}


def _normalize_reason(reason: str | None) -> str:
    if reason is None:
        raise ValueError("reason must be provided")
    key = str(reason).strip().lower()
    if not key:
        raise ValueError("reason must be provided")
    return key


def _extract_class_name(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("class", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _set_scalar_ions(target: MutableMapping[str, Any], amount: int) -> None:
    target["ions"] = int(amount)
    target["Ions"] = int(amount)


def _update_map_entry(
    target: MutableMapping[str, Any],
    map_key: str,
    cls_name: str,
    amount: int,
) -> None:
    raw_map = target.get(map_key)
    if isinstance(raw_map, MutableMapping):
        map_obj: MutableMapping[str, Any] = raw_map
    else:
        map_obj = {}
        target[map_key] = map_obj
    map_obj[str(cls_name)] = int(amount)


def grant_starting_ions(
    player: MutableMapping[str, Any],
    reason: str,
    *,
    state: MutableMapping[str, Any] | None = None,
) -> int:
    """Set the player's starting ions for ``reason`` and mirror shared state."""

    if not isinstance(player, MutableMapping):
        raise TypeError("player must be a mapping")

    reason_key = _normalize_reason(reason)
    try:
        amount = int(START_IONS[reason_key])
    except KeyError as exc:  # pragma: no cover - defensive, validated above
        raise ValueError(f"Unknown starting-ion reason: {reason}") from exc

    cls_name = _extract_class_name(player)

    _set_scalar_ions(player, amount)
    if cls_name:
        _update_map_entry(player, "ions_by_class", cls_name, amount)

    if state is not None and isinstance(state, MutableMapping):
        if cls_name:
            _update_map_entry(state, "ions_by_class", cls_name, amount)
        players = state.get("players")
        if isinstance(players, list):
            for entry in players:
                if not isinstance(entry, MutableMapping):
                    continue
                if entry is player:
                    continue
                entry_cls = _extract_class_name(entry)
                if entry_cls == cls_name:
                    _set_scalar_ions(entry, amount)
                    if cls_name:
                        _update_map_entry(entry, "ions_by_class", cls_name, amount)

    return amount


__all__ = ["START_IONS", "grant_starting_ions"]
