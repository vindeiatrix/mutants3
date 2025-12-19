"""Helpers for resolving what the player can sense nearby."""
from __future__ import annotations

from typing import Any, Iterable, Iterator, Mapping, Sequence

Direction = str

# Canonical direction names displayed to the player.  The keys are the normalized
# short-form tokens used by the UI renderer; the values are the human readable
# phrases that appear in shadow lines.
_DIRECTION_NAMES: dict[str, str] = {
    "N": "north",
    "S": "south",
    "E": "east",
    "W": "west",
    "NE": "northeast",
    "NW": "northwest",
    "SE": "southeast",
    "SW": "southwest",
}

# Display order used when presenting multiple directions.  The sequence runs
# clockwise starting from east so that cardinal directions appear in their
# classic BBS order with the diagonals grouped beside their parent direction.
_DISPLAY_ORDER: tuple[str, ...] = ("E", "NE", "SE", "S", "SW", "W", "NW", "N")
_DISPLAY_ORDER_INDEX = {direction: index for index, direction in enumerate(_DISPLAY_ORDER)}
_CARDINAL_DIRECTIONS = {"N", "S", "E", "W"}

# Build an alias table so that short-form, uppercase, lowercase, and long-form
# strings all resolve to the same canonical direction token.
_ALIAS: dict[str, str] = {}
for token, label in _DIRECTION_NAMES.items():
    _ALIAS[token] = token
    _ALIAS[token.lower()] = token
    _ALIAS[label] = token
    _ALIAS[label.title()] = token
    _ALIAS[label.upper()] = token


def _iter_direction_tokens(payload: Iterable[Any]) -> Iterator[Any]:
    """Yield potential direction tokens from *payload* safely."""

    for value in payload:
        if isinstance(value, (str, bytes)):
            token = value.decode() if isinstance(value, bytes) else value
            if token:
                yield token
        elif value is not None:
            # Attempt to coerce other primitive values to strings; ignore objects
            # like mappings or sequences because they are unlikely to represent
            # direction identifiers.
            if isinstance(value, (int, float)):
                yield str(value)


def canonical_direction(token: Any) -> str | None:
    """Return the canonical short-form direction for *token* or ``None``.

    The helper accepts the compact tokens (``"NE"``), their lowercase variants,
    or the long names (``"northwest"``).  Unknown inputs return ``None``.
    """

    if token is None:
        return None
    if isinstance(token, str):
        key = token.strip()
    elif isinstance(token, bytes):
        try:
            key = token.decode()
        except Exception:
            return None
    else:
        key = str(token)
    if not key:
        return None
    return _ALIAS.get(key) or _ALIAS.get(key.lower())


def direction_word(token: Any) -> str:
    """Return the human readable name for *token*.

    Unknown tokens fall back to the lowercase string representation so that
    callers never raise while formatting UI text.
    """

    canonical = canonical_direction(token)
    if canonical is None:
        return str(token).strip().lower()
    return _DIRECTION_NAMES[canonical]


def normalize_directions(directions: Iterable[Any]) -> list[str]:
    """Return a normalized, deduplicated, and ordered list of directions."""

    seen: set[str] = set()
    normalized: list[str] = []
    for token in _iter_direction_tokens(directions):
        canonical = canonical_direction(token)
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)

    normalized.sort(key=lambda d: _DISPLAY_ORDER_INDEX.get(d, len(_DISPLAY_ORDER)))
    return normalized


def adjacent_monster_directions(monsters: Any, player_pos: Sequence[int] | Mapping[str, Any] | None) -> list[str]:
    """Return normalized adjacent monster directions for *player_pos*.

    The function defers to ``monsters.list_adjacent_monsters`` when available
    and gracefully handles missing APIs or runtime errors by returning an empty
    list.
    """

    if player_pos is None or monsters is None:
        return []
    api = getattr(monsters, "list_adjacent_monsters", None)
    if not callable(api):
        return []
    try:
        raw = api(player_pos)  # type: ignore[misc]
    except Exception:
        return []
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        payload: Iterable[Any] = [raw]
    elif isinstance(raw, Iterable):
        payload = raw
    else:
        payload = [raw]
    normalized = normalize_directions(payload)
    return [direction for direction in normalized if direction in _CARDINAL_DIRECTIONS]


__all__ = [
    "Direction",
    "adjacent_monster_directions",
    "canonical_direction",
    "direction_word",
    "normalize_directions",
]
