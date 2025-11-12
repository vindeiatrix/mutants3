from __future__ import annotations

from typing import Optional

from ...registries import items_catalog, items_instances as itemsreg
from ...services import item_transfer as itx
from ...services import player_state as pstate
from ...util.textnorm import normalize_item_query as normalize


def inventory_iids_for_active_player(ctx) -> list[str]:
    p = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(p, ctx)
    pstate.bind_inventory_to_active_class(p)
    itx._ensure_inventory(p)
    inv = [str(i) for i in (p.get("inventory") or []) if i]
    equipped = pstate.get_equipped_armour_id(p)
    if equipped:
        inv = [iid for iid in inv if iid != equipped]
    return inv


def resolve_item_arg(ctx, token: str) -> Optional[str]:
    q = normalize(token)
    if not q:
        return None
    inv = inventory_iids_for_active_player(ctx)
    cat = items_catalog.load_catalog()
    for iid in inv:
        inst = itemsreg.get_instance(iid) or {}
        tpl = cat.get(inst.get("item_id")) or {}
        key = normalize(tpl.get("name") or tpl.get("item_id") or "")
        if key.startswith(q):
            return iid
    return None
