from __future__ import annotations

from typing import Optional

from ...registries import items_catalog, items_instances as itemsreg
from ...services import item_transfer as itx
from ...services import player_state as pstate
from ...bootstrap.lazyinit import ensure_player_state
from ...ui.item_display import canonical_name
from ...util.textnorm import normalize_item_query as normalize


def inventory_iids_for_active_player(ctx) -> list[str]:
    # Use the canonical active player from the persisted state so inventory lookups
    # stay in sync across different storage backends (JSON/SQLite) and contexts.
    state = ensure_player_state(ctx)
    state, player = pstate.get_active_pair(state)
    pstate.ensure_active_profile(state, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    inv = [str(i) for i in (player.get("inventory") or []) if i]
    equipped = pstate.get_equipped_armour_id(player)
    if equipped:
        inv = [iid for iid in inv if iid != equipped]
    return inv


def resolve_item_arg(ctx, token: str) -> Optional[str]:
    q = normalize(token)
    if not q:
        return None
    inv = inventory_iids_for_active_player(ctx)
    try:
        cat = items_catalog.load_catalog()
    except (FileNotFoundError, ValueError):
        cat = None

    for iid in inv:
        inst = itemsreg.get_instance(iid) or {}
        item_id = str(inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or "")
        tpl_obj = cat.get(item_id) if cat else {}
        tpl = tpl_obj if isinstance(tpl_obj, dict) else {}

        candidates = (
            tpl.get("name"),
            tpl.get("item_id"),
            inst.get("display_name"),
            inst.get("name"),
            item_id,
            canonical_name(item_id) if item_id else "",
        )

        for candidate in candidates:
            key = normalize(candidate or "")
            if key and key.startswith(q):
                return iid
        # When the catalog entry is missing or malformed, fall back to a last-ditch
        # canonical name derived from the raw instance payload.
        derived_id = str(inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or "")
        key = normalize(canonical_name(derived_id) if derived_id else "")
        if key and key.startswith(q):
            return iid
    return None
