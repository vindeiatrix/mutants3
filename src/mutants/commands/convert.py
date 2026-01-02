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


def _purge_iid_everywhere(state: dict, iid: str) -> None:
    """Remove ``iid`` from all inventories/bags/active views in ``state``."""

    if not isinstance(state, dict):
        return
    sanitized = str(iid).strip()
    if not sanitized:
        return

    def _drop_from_list(lst):
        if isinstance(lst, list):
            return [tok for tok in lst if str(tok).strip() != sanitized]
        return lst

    state["inventory"] = _drop_from_list(state.get("inventory"))
    active = state.get("active")
    if isinstance(active, dict):
        active["inventory"] = _drop_from_list(active.get("inventory"))

    bags = state.get("bags")
    if isinstance(bags, dict):
        for key, bag in list(bags.items()):
            bags[key] = _drop_from_list(bag)

    players = state.get("players")
    if isinstance(players, list):
        for pl in players:
            if not isinstance(pl, dict):
                continue
            pl["inventory"] = _drop_from_list(pl.get("inventory"))
            # Mirror bags if present at player level.
            pbags = pl.get("bags")
            if isinstance(pbags, dict):
                for key, bag in list(pbags.items()):
                    pbags[key] = _drop_from_list(bag)


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

    runtime_cls = klass if isinstance(klass, str) and klass else pstate.get_active_class(player)
    if snapshot_state is not None:
        ion_map = snapshot_state.get("ions_by_class")
        if isinstance(ion_map, dict) and isinstance(runtime_cls, str) and runtime_cls in ion_map:
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
        klass = runtime_cls or pstate.get_active_class(player)

    new_total = max(0, before + value)

    inventory = list(player.get("inventory") or [])
    try:
        inventory.remove(iid)
    except ValueError:
        pass
    player["inventory"] = inventory
    _purge_iid_everywhere(player, iid)

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
        # Preserve current runtime state (including position) when persisting.
        runtime_state = ctx.get("player_state") if isinstance(ctx, dict) else None
        if isinstance(runtime_state, dict):
            state = dict(runtime_state)
        else:
            state = pstate.load_state()
        if not isinstance(state, dict):
            state = {}

        # Force the active identity/class to the current player so persistence does not bleed
        # into a different class when the on-disk active_id is stale.
        player_id = player.get("id")
        if player_id:
            state["active_id"] = player_id
        if runtime_cls:
            state["class"] = runtime_cls

        pstate.ensure_class_profiles(state)
        pstate.normalize_player_state_inplace(state)
        # Keep canonical position in sync with runtime.
        if isinstance(runtime_state, dict):
            try:
                pos = pstate.canonical_player_pos(runtime_state)
                pstate.update_player_pos(state, runtime_cls, pos)
            except Exception:
                pass

        # 1. Persist inventory change for the current class, not whatever is on disk.
        target_cls = runtime_cls or pstate.get_active_class(state)
        pstate.update_player_inventory(state, target_cls, player["inventory"])
        _purge_iid_everywhere(state, iid)

        # 2. Persist ion change (set_ions_for_active saves the full state)
        # Ensure the active class reflects the target class so ions land in the right bucket.
        if target_cls:
            state["class"] = target_cls
        pstate.set_ions_for_active(state, new_total)

        # 3. Update runtime context so the game loop sees the changes.
        if isinstance(ctx, dict):
            ctx["player_state"] = state
            ctx.pop("_runtime_player", None)
            player_ctx = pstate.ensure_player_state(ctx)
            if isinstance(player_ctx, dict):
                # Keep the runtime cache aligned with the persisted state to
                # avoid re-saving a stale inventory via the turn scheduler.
                player_ctx["inventory"] = list(player.get("inventory") or [])
                bags_map = player_ctx.setdefault("bags", {})
                bags_map[str(klass)] = list(player_ctx["inventory"])
                player_ctx["_dirty"] = False

        if pstate._pdbg_enabled():
            pstate._pdbg_setup_file_logging()
            LOG_P.info(
                "[playersdbg] CONVERT success class=%s ions=%s add=%s",
                runtime_cls or klass,
                new_total,
                value,
            )
    except Exception:
        bus.push("SYSTEM/WARN", "Failed to save conversion results.")
        return {"ok": False, "reason": "save_error"}

    name = _display_name(item_id, catalog)
    bus.push("COMBAT/INFO", f"The {name} vanishes with a flash!\nYou convert the {name} into {value} ions.")
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
