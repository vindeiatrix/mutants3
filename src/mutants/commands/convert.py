from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..services import item_transfer as itx
from ..services import player_state as pstate
from mutants.debug import turnlog
from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..util.textnorm import normalize_item_query


LOG_P = logging.getLogger("mutants.playersdbg")

def _legacy_ions(payload: Dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("Ions", "ions"):
        if key in payload:
            try:
                return int(payload[key])
            except Exception:
                return 0
    stats = payload.get("stats")
    if isinstance(stats, dict):
        for key in ("Ions", "ions"):
            if key in stats:
                try:
                    return int(stats[key])
                except Exception:
                    return 0
    return 0


def _resolve_meta(catalog: Any, item_id: str) -> Dict[str, object]:
    getter = getattr(catalog, "get", None)
    if callable(getter):
        try:
            meta = getter(str(item_id))
        except Exception:
            meta = None
        if isinstance(meta, dict):
            return meta
    if isinstance(catalog, dict):
        meta = catalog.get(str(item_id))
        if isinstance(meta, dict):
            return meta
    return {}


def _display_name(item_id: str, catalog: Any) -> str:
    meta = _resolve_meta(catalog, item_id)
    return str(meta.get("display") or meta.get("name") or item_id)


def _base_convert_value(item_id: str, catalog: Any) -> Tuple[int, bool]:
    """Return the catalog conversion value ignoring instance state."""

    meta = _resolve_meta(catalog, item_id)
    if not meta:
        return 0, False

    for key in ("convert_ions", "ion_value", "value"):
        if key in meta:
            try:
                return int(meta[key]), True
            except Exception:
                return 0, False

    return 0, False


def _convert_value(item_id: str, catalog: Any, iid: Optional[str] = None) -> int:
    base_value, defined = _base_convert_value(item_id, catalog)
    if not defined:
        return 0

    if not iid:
        return base_value

    try:
        level = itemsreg.get_enchant_level(iid)
    except Exception:
        level = 0

    return base_value + _enchant_convert_bonus(level)


def _enchant_convert_bonus(level: int) -> int:
    try:
        normalized = int(level)
    except (TypeError, ValueError):
        normalized = 0
    if normalized <= 0:
        return 0
    return 10100 * normalized


def _convert_payout(iid: str, item_id: str, catalog: Any) -> int:
    return _convert_value(item_id, catalog, iid if iid else None)


def _choose_inventory_item(
    player: Dict[str, object],
    prefix: str,
    catalog: Any,
) -> Tuple[Optional[str], Optional[str]]:
    inventory: List[str] = [str(i) for i in (player.get("inventory") or []) if i]
    equipped = pstate.get_equipped_armour_id(player)
    if equipped:
        inventory = [iid for iid in inventory if iid != equipped]
    if not inventory:
        return None, None

    query = normalize_item_query(prefix).lower()
    if not query:
        return None, None

    candidates: List[Tuple[str, str]] = []
    for iid in inventory:
        inst = itemsreg.get_instance(iid)
        if not inst:
            continue
        # Origin-agnostic; decide by value instead
        item_id = (
            inst.get("item_id")
            or inst.get("catalog_id")
            or inst.get("id")
            or iid
        )
        candidates.append((str(iid), str(item_id)))

    matches: List[Tuple[str, str]] = []
    for iid, item_id in candidates:
        name = _display_name(item_id, catalog).lower()
        if item_id.lower().startswith(query) or name.startswith(query):
            matches.append((iid, item_id))

    if not matches:
        return None, None

    exact = [m for m in matches if m[1].lower() == query or _display_name(m[1], catalog).lower() == query]
    return exact[0] if exact else matches[0]


def convert_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    prefix = (arg or "").strip()
    if not prefix:
        bus.push("SYSTEM/WARN", "Usage: convert <item>")
        return {"ok": False, "reason": "missing_argument"}

    catalog = catreg.load_catalog() or {}
    player = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    iid, item_id = _choose_inventory_item(player, prefix, catalog)
    if not iid or not item_id:
        bus.push("SYSTEM/WARN", f"You're not carrying a {prefix}.")
        return {"ok": False, "reason": "not_found"}

    base_value, defined = _base_convert_value(item_id, catalog)
    value = _convert_payout(iid, item_id, catalog)
    if not defined:
        bus.push("SYSTEM/WARN", "You can't convert that.")
        return {"ok": False, "reason": "not_convertible"}

    if base_value <= 0:
        name = _display_name(item_id, catalog)
        bus.push("SYSTEM/WARN", f"No conversion value set for the {name}.")
        return {"ok": False, "reason": "no_conversion_value"}

    if value <= 0:
        bus.push("SYSTEM/WARN", "You can't convert that.")
        return {"ok": False, "reason": "not_convertible"}

    before = _legacy_ions(player)
    klass = pstate.get_active_class(player)

    try:
        snapshot_state = pstate.load_state()
    except Exception:
        snapshot_state = None

    if snapshot_state is not None:
        klass_from_state = pstate.get_active_class(snapshot_state)
        if isinstance(klass_from_state, str) and klass_from_state:
            klass = klass_from_state
        ion_map = snapshot_state.get("ions_by_class")
        if isinstance(ion_map, dict) and isinstance(klass, str) and klass in ion_map:
            state_before = pstate.get_ions_for_active(snapshot_state)
            if before:
                before = min(before, state_before)
            else:
                before = state_before
        else:
            alt = _legacy_ions(snapshot_state)
            if alt or before == 0:
                before = alt

    if not isinstance(klass, str) or not klass:
        klass = pstate.get_active_class(player)

    new_total = max(0, before + value)

    inventory = list(player.get("inventory") or [])
    try:
        inventory.remove(iid)
    except ValueError:
        pass
    player["inventory"] = inventory

    player["ions"] = new_total
    player["Ions"] = new_total
    active_profile = player.get("active")
    if isinstance(active_profile, dict):
        active_profile["ions"] = new_total
        active_profile["Ions"] = new_total
    stats = player.get("stats")
    if isinstance(stats, dict):
        stats["ions"] = new_total
        stats["Ions"] = new_total
    if isinstance(klass, str) and klass:
        player["ions_by_class"] = {str(klass): new_total}

    itemsreg.remove_instance(iid)

    try:
        state = pstate.load_state()
        
        # 1. Persist inventory change
        active_class = pstate.get_active_class(player)
        pstate.update_player_inventory(state, active_class, player["inventory"])
        
        # 2. Persist ion change (set_ions_for_active saves the full state)
        pstate.set_ions_for_active(state, new_total)
        # 3. Update runtime context so the game loop sees the changes!
        if "player_state" in ctx:
            ctx["player_state"] = state
        # Force reload of the active player object on next access
        if "_runtime_player" in ctx:
            del ctx["_runtime_player"]

        if pstate._pdbg_enabled():
            pstate._pdbg_setup_file_logging()
            LOG_P.info(
                "[playersdbg] CONVERT success class=%s ions=%s add=%s",
                active_class,
                new_total,
                value,
            )
    except Exception:
        bus.push("SYSTEM/WARN", "Failed to save conversion results.")
        return {"ok": False, "reason": "save_error"}

    name = _display_name(item_id, catalog)
    bus.push("SYSTEM/OK", f"The {name} vanishes with a flash!")
    bus.push("SYSTEM/OK", f"You convert the {name} into {value} ions.")
    turnlog.emit(
        ctx,
        "ITEM/CONVERT",
        owner="player",
        item_id=item_id,
        item_name=name,
        iid=iid,
        ions=value,
        source="player",
    )

    return {"ok": True, "iid": iid, "item_id": item_id, "ions": value}


def register(dispatch, ctx) -> None:
    dispatch.register("convert", lambda arg: convert_cmd(arg, ctx))
