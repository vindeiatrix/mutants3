from __future__ import annotations
from typing import Optional

from mutants.app import advance_invalid_turn as app_advance_invalid_turn
from ..services import item_transfer as itx
from ..services import player_state as pstate

from ._util.items import inventory_iids_for_active_player, resolve_item_arg


def find_inventory_item_by_prefix(ctx, token: str) -> Optional[str]:
    return resolve_item_arg(ctx, token)


def advance_invalid_command_turn(
    ctx, token: str, resolved: Optional[str] = None
) -> bool:
    """Advance the shared turn tracker for unknown/invalid commands.

    Returns ``True`` if the call was handled by a :class:`TurnScheduler`.
    """

    return app_advance_invalid_turn(token, ctx=ctx, resolved=resolved)
