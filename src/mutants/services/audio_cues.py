"""Utilities for propagating monster audio cues to the UI."""
from __future__ import annotations

from collections import deque
from typing import Any, Deque, Iterable, List, Mapping, MutableMapping, Sequence

from mutants.world import vision

__all__ = ["emit_sound", "drain", "peek"]


_STORE_KEY = "_audio_cues_queue"
_STORE_POS_KEY = "_audio_cues_queue_pos"
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


def _resolve_store(ctx: Any, *, create: bool) -> Deque[tuple[str, tuple[int, int, int] | None]] | None:
    if ctx is None:
        return None
    queue: Deque[tuple[str, tuple[int, int, int] | None]] | None = None
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
    movement: tuple[int, int] | None = None,
    once_per_frame: bool = True,
) -> str | None:
    """Format and store an audio cue for *kind* if the player can hear it.

    When ``monster_pos`` and ``player_pos`` are co-located, ``movement`` may be
    provided to hint at the direction from which the monster approached.
    """

    monster = _coerce_pos(monster_pos)
    player = _coerce_pos(player_pos)
    if monster is None or player is None:
        return None
    if monster[0] != player[0]:
        return None

    dist = _distance(monster, player)
    if dist > _MAX_DISTANCE:
        return None

    label = _sound_label(kind)
    # Special-case combined phrasing used in reference.
    if label == "yelling":
        label = "yelling and screaming"

    if dist == 0:
        # Reference does not emit a cue when co-located; suppress the adjacent variant.
        return None
    else:
        dx = monster[1] - player[1]
        dy = monster[2] - player[2]
        token = _direction_token(dx, dy)
        if token is None:
            return None
        direction = vision.direction_word(token)
        if dist > 1:
            message = f"You hear faint sounds of {label} far to the {direction}."
        else:
            message = f"You hear loud sounds of {label} to the {direction}."

    queue = _resolve_store(ctx, create=True)
    if queue is not None:
        existing_msgs = [entry[0] for entry in queue]
        if once_per_frame and message in existing_msgs:
            return message
        # Avoid piling up duplicate cues within the same tick/frame.
        if not queue or queue[-1][0] != message:
            queue.append((message, player))
            # When hearing a monster at distance > 1, suppress shadows for the next render
            # so they appear a frame later.
            try:
                if dist > 1 and isinstance(ctx, MutableMapping):
                    ctx["_suppress_shadows_once"] = True
            except Exception:
                pass
    return message


def drain(ctx: Any) -> List[str]:
    """Return and clear pending audio cues stored on *ctx*."""

    queue = _resolve_store(ctx, create=False)
    if not queue:
        return []
    items = []
    seen: set[str] = set()
    current_pos = None
    if isinstance(ctx, MutableMapping):
        try:
            from mutants.services import player_state as pstate

            current_pos = pstate.canonical_player_pos(ctx.get("player_state"))
        except Exception:
            current_pos = None
    while queue:
        msg, pos = queue.popleft()
        if current_pos and pos and current_pos[0] != pos[0]:
            # Drop cross-year cues to avoid stale hints after travel.
            continue
        if msg in seen:
            continue
        seen.add(msg)
        items.append(msg)
    queue.clear()
    return items


def peek(ctx: Any) -> List[str]:
    """Return the pending audio cues without clearing the queue."""

    queue = _resolve_store(ctx, create=False)
    if not queue:
        return []
    return [entry[0] for entry in list(queue)]
