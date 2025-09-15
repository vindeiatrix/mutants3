from __future__ import annotations
from typing import Optional

from ..registries import items_catalog, items_instances as itemsreg
from ..util.textnorm import normalize_item_query as normalize
from ..services import item_transfer as itx


def inventory_iids_for_active_player(ctx) -> list[str]:
    p = itx._load_player()
    inv = p.get("inventory") or []
    return [str(i) for i in inv]


def find_inventory_item_by_prefix(ctx, token: str) -> Optional[str]:
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
