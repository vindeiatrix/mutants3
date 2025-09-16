from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from typing import Any, List

InventoryEntry = Any


def _player_file() -> str:
    return os.path.join(os.getcwd(), "state", "playerlivestate.json")


def _load_player_state() -> Mapping[str, Any]:
    try:
        with open(_player_file(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return data if isinstance(data, Mapping) else {}


def _ensure_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, set):
        return list(raw)
    return [raw]


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "no", "0"}
    return bool(value)


def _should_skip(entry: Any, excluded_slots: set[str]) -> bool:
    if not excluded_slots:
        return False
    if not isinstance(entry, Mapping):
        return False
    if not _truthy(entry.get("equipped")):
        return False
    slot = entry.get("slot")
    if slot is None:
        return False
    return str(slot) in excluded_slots


def get_player_inventory_instances(
    ctx: Any,
    *,
    exclude_equipped_slots: Iterable[str] | None = None,
) -> List[InventoryEntry]:
    """Return the authoritative list of inventory entries for the active player."""

    player_state = _load_player_state()
    raw_inventory = player_state.get("inventory") if isinstance(player_state, Mapping) else []
    entries = _ensure_list(raw_inventory)

    excluded_slots = (
        {str(slot) for slot in exclude_equipped_slots if slot is not None}
        if exclude_equipped_slots
        else set()
    )

    if not excluded_slots:
        return entries

    filtered: list[Any] = []
    for entry in entries:
        if _should_skip(entry, excluded_slots):
            continue
        filtered.append(entry)
    return filtered
