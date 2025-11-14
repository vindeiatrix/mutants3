from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from mutants.app import advance_invalid_turn as app_advance_invalid_turn
from mutants.bootstrap.lazyinit import ensure_player_state
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


def resolve_ready_target_in_tile(ctx) -> Optional[str]:
    """Return the ready target's instance_id iff it’s in the player’s current tile."""
    p = ensure_player_state(ctx)
    if not isinstance(p, dict):
        return None

    target_raw = p.get("ready_target") or p.get("target_monster_id")
    target = str(target_raw).strip() if target_raw else ""
    if not target:
        return None

    year, x, y = pstate.canonical_player_pos(p)

    monsters = None
    if isinstance(ctx, Mapping):
        monsters = ctx.get("monsters")
    else:
        monsters = getattr(ctx, "monsters", None)
    if monsters is None:
        return None

    list_at = getattr(monsters, "list_at", None)
    if not callable(list_at):
        return None

    try:
        entries = list_at(year, x, y)
    except Exception:
        return None

    for m in entries or []:
        if not isinstance(m, Mapping):
            continue
        mid_raw = m.get("id") or m.get("instance_id") or m.get("monster_id")
        mid = str(mid_raw).strip() if mid_raw else ""
        if mid == target:
            return mid
    return None
