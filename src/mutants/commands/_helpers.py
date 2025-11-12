from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any, Optional

from mutants.app import advance_invalid_turn as app_advance_invalid_turn
from mutants.services import player_state as pstate
from ._util.items import resolve_item_arg


def find_inventory_item_by_prefix(ctx, token: str) -> Optional[str]:
    return resolve_item_arg(ctx, token)


def advance_invalid_command_turn(
    ctx, token: str, resolved: Optional[str] = None
) -> bool:
    """Advance the shared turn tracker for unknown/invalid commands.

    Returns ``True`` if the call was handled by a :class:`TurnScheduler`.
    """

    return app_advance_invalid_turn(token, ctx=ctx, resolved=resolved)


def _ensure_state(ctx: Any) -> Mapping[str, Any] | dict[str, Any]:
    if isinstance(ctx, Mapping):
        state = ctx.get("player_state")
        if isinstance(state, Mapping):
            return state
    try:
        state = pstate.load_state()
    except Exception:
        state = {}
    if isinstance(ctx, MutableMapping):
        try:
            ctx.setdefault("player_state", state)  # type: ignore[index]
        except Exception:
            pass
    return state if isinstance(state, Mapping) else {}


def _sanitize_target(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _extract_pos(payload: Mapping[str, Any] | None) -> Optional[tuple[int, int, int]]:
    if not isinstance(payload, Mapping):
        return None
    pos = payload.get("pos") or payload.get("position")
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            return int(pos[0]), int(pos[1]), int(pos[2])
        except (TypeError, ValueError):
            return None
    return None


def resolve_ready_target_in_tile(ctx) -> Optional[str]:
    p = _ensure_state(ctx)  # see Task 3
    active = p.get("active") if isinstance(p, Mapping) else None

    target = None
    if isinstance(active, Mapping):
        target = _sanitize_target(
            active.get("ready_target") or active.get("target_monster_id")
        )
    if target is None and isinstance(p, Mapping):
        target = _sanitize_target(p.get("ready_target") or p.get("target_monster_id"))
    if not target:
        return None

    pos = _extract_pos(active) or _extract_pos(p if isinstance(p, Mapping) else None)
    if pos is None:
        return None

    monsters = None
    if isinstance(ctx, Mapping):
        monsters = ctx.get("monsters")
    if monsters is None:
        return None
    list_at = getattr(monsters, "list_at", None)
    if not callable(list_at):
        return None

    year, x, y = pos
    try:
        entries = list_at(year, x, y)
    except Exception:
        return None

    for monster in entries or []:
        if not isinstance(monster, Mapping):
            continue
        mid = _sanitize_target(
            monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
        )
        if mid and mid == target:
            return mid
    return None
