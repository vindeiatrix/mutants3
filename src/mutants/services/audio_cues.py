"""Utilities for propagating monster audio cues to the UI."""
from __future__ import annotations

from collections import deque
from typing import Any, Deque, Iterable, List, Mapping, MutableMapping, Sequence

from mutants.world import vision

__all__ = ["emit_sound", "drain", "peek"]


_STORE_KEY = "_audio_cues_queue"
_MAX_DISTANCE = 4

_SOUND_LABELS: Mapping[str, str] = {
    "footstep": "footsteps",
    "footsteps": "footsteps",
    "steps": "footsteps",
    "step": "footsteps",
    "yell": "yelling",
    "yelling": "yelling",
    "yells": "yelling",
    "scream": "yelling",
    "screaming": "yelling",
}


def _coerce_pos(value: Any) -> tuple[int, int, int] | None:
    """Best-effort coercion of *value* to a ``(year, x, y)`` tuple."""

    coords: Iterable[Any]
    if isinstance(value, Mapping):
        coords = (value.get("year"), value.get("x"), value.get("y"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        coords = value
    else:
        return None

    raw = list(coords)
    if len(raw) != 3:
        return None
    try:
        year, x, y = int(raw[0]), int(raw[1]), int(raw[2])
    except (TypeError, ValueError):
        return None
    return year, x, y


def _direction_token(dx: int, dy: int) -> str | None:
    if dx == 0 and dy == 0:
        return None
    step_x = 0 if dx == 0 else (1 if dx > 0 else -1)
    step_y = 0 if dy == 0 else (1 if dy > 0 else -1)
    if step_x == 0:
        return "N" if step_y > 0 else "S"
    if step_y == 0:
        return "E" if step_x > 0 else "W"
    if step_x > 0 and step_y > 0:
        return "NE"
    if step_x > 0 and step_y < 0:
        return "SE"
    if step_x < 0 and step_y > 0:
        return "NW"
    return "SW"


def _sound_label(kind: Any) -> str:
    if isinstance(kind, str):
        token = kind.strip().lower()
    else:
        token = str(kind).strip().lower() if kind is not None else ""
    if not token:
        return "sounds"
    return _SOUND_LABELS.get(token, token)


def _resolve_store(ctx: Any, *, create: bool) -> Deque[str] | None:
    if ctx is None:
        return None
    queue: Deque[str] | None = None
    if isinstance(ctx, MutableMapping):
        candidate = ctx.get(_STORE_KEY)
        if isinstance(candidate, deque):
            queue = candidate
        elif create:
            queue = deque()
            ctx[_STORE_KEY] = queue
    else:
        candidate = getattr(ctx, _STORE_KEY, None)
        if isinstance(candidate, deque):
            queue = candidate
        elif create:
            queue = deque()
            try:
                setattr(ctx, _STORE_KEY, queue)
            except Exception:
                queue = None
    return queue


def _distance(monster: tuple[int, int, int], player: tuple[int, int, int]) -> int:
    dx = monster[1] - player[1]
    dy = monster[2] - player[2]
    return max(abs(dx), abs(dy))


def emit_sound(
    monster_pos: Any,
    player_pos: Any,
    kind: Any,
    *,
    ctx: Any | None = None,
) -> str | None:
    """Format and store an audio cue for *kind* if the player can hear it."""

    monster = _coerce_pos(monster_pos)
    player = _coerce_pos(player_pos)
    if monster is None or player is None:
        return None
    if monster[0] != player[0]:
        return None

    dist = _distance(monster, player)
    if dist == 0 or dist > _MAX_DISTANCE:
        return None

    dx = monster[1] - player[1]
    dy = monster[2] - player[2]
    token = _direction_token(dx, dy)
    if token is None:
        return None

    direction = vision.direction_word(token)
    label = _sound_label(kind)
    qualifier = " far" if dist > 1 else ""
    message = f"You hear {label}{qualifier} to the {direction}."

    queue = _resolve_store(ctx, create=True)
    if queue is not None:
        queue.append(message)
    return message


def drain(ctx: Any) -> List[str]:
    """Return and clear pending audio cues stored on *ctx*."""

    queue = _resolve_store(ctx, create=False)
    if not queue:
        return []
    items = list(queue)
    queue.clear()
    return items


def peek(ctx: Any) -> List[str]:
    """Return the pending audio cues without clearing the queue."""

    queue = _resolve_store(ctx, create=False)
    if not queue:
        return []
    return list(queue)
