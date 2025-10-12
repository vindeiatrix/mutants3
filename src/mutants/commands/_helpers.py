from __future__ import annotations
from typing import Optional

from ..services import item_transfer as itx
from ..services import player_state as pstate

from ._util.items import inventory_iids_for_active_player, resolve_item_arg


def find_inventory_item_by_prefix(ctx, token: str) -> Optional[str]:
    return resolve_item_arg(ctx, token)
