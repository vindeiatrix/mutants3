"""Helpers for tracking player targets across monster AI ticks."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence, Set

from mutants.services import combat_loot

__all__ = [
    "record_target_position",
    "update_target_positions",
]


def _ensure_ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    payload = monster.get("_ai_state")
    if isinstance(payload, MutableMapping):
        return payload
    if isinstance(payload, Mapping):
        state: MutableMapping[str, Any] = dict(payload)
    else:
        state = {}
    monster["_ai_state"] = state
    return state


def _target_positions_map(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    state = _ensure_ai_state(monster)
    raw_map = state.get("target_positions")
    if isinstance(raw_map, MutableMapping):
        return raw_map
    if isinstance(raw_map, Mapping):
        mapping: MutableMapping[str, Any] = dict(raw_map)
    else:
        mapping = {}
    state["target_positions"] = mapping
    return mapping


def _normalize_player_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        return token or None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _normalize_pos(value: Any) -> tuple[int, int, int] | None:
    return combat_loot.coerce_pos(value)


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        token = _normalize_player_id(monster.get(key))
        if token:
            return token
    return "?"


def record_target_position(
    monster: MutableMapping[str, Any],
    player_id: str,
    player_pos: Sequence[int] | Mapping[str, Any],
) -> bool:
    """Persist the last known ``player_pos`` for ``player_id`` on ``monster``.

    Returns ``True`` when the target has just re-entered the monster's current
    location after being away. ``False`` otherwise.
    """

    if not isinstance(monster, MutableMapping):
        return False

    target_id = _normalize_player_id(player_id)
    if not target_id:
        return False

    normalized_pos = _normalize_pos(player_pos)
    if normalized_pos is None:
        return False

    monster_pos = _normalize_pos(monster.get("pos"))
    co_located = monster_pos is not None and monster_pos == normalized_pos

    mapping = _target_positions_map(monster)
    previous = mapping.get(target_id)
    was_collocated = False
    if isinstance(previous, Mapping):
        was_collocated = bool(previous.get("co_located"))

    mapping[target_id] = {
        "pos": list(normalized_pos),
        "co_located": co_located,
    }

    return bool(previous) and (not was_collocated) and co_located


def _iter_monsters(monsters: Any) -> Iterable[MutableMapping[str, Any]]:
    if monsters is None:
        return []

    if hasattr(monsters, "list_all"):
        try:
            entries = monsters.list_all()  # type: ignore[attr-defined]
        except Exception:
            entries = []
    elif isinstance(monsters, Sequence) and not isinstance(monsters, (str, bytes)):
        entries = monsters
    else:
        entries = []

    result: list[MutableMapping[str, Any]] = []
    for entry in entries:
        if isinstance(entry, MutableMapping):
            result.append(entry)
    return result


def update_target_positions(
    monsters: Any,
    player_id: str,
    player_pos: Sequence[int] | Mapping[str, Any],
) -> Set[str]:
    """Update all monsters that are targeting ``player_id``.

    Returns the set of monster identifiers whose target just re-entered their
    location this tick.
    """

    normalized_player = _normalize_player_id(player_id)
    normalized_pos = _normalize_pos(player_pos)
    if normalized_player is None or normalized_pos is None:
        return set()

    reentries: Set[str] = set()

    for monster in _iter_monsters(monsters):
        target = _normalize_player_id(monster.get("target_player_id"))
        if target != normalized_player:
            continue
        if record_target_position(monster, normalized_player, normalized_pos):
            monster_ident = _monster_id(monster)
            if monster_ident:
                reentries.add(monster_ident)

    return reentries

