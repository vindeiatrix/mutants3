from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..services import item_transfer as itx
from ..services import player_state as pstate
from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..util.textnorm import normalize_item_query


def _get_ions(player: Dict[str, object]) -> int:
    if "Ions" in player:
        try:
            return int(player["Ions"])
        except Exception:
            return 0
    if "ions" in player:
        try:
            return int(player["ions"])
        except Exception:
            return 0
    stats = player.get("stats")
    if isinstance(stats, dict):
        if "Ions" in stats:
            try:
                return int(stats["Ions"])
            except Exception:
                return 0
        if "ions" in stats:
            try:
                return int(stats["ions"])
            except Exception:
                return 0
    return 0


def _set_ions(player: Dict[str, object], value: int) -> None:
    clamped = int(max(0, value))
    if "Ions" in player:
        player["Ions"] = clamped
        return
    if "ions" in player:
        player["ions"] = clamped
        return
    stats = player.get("stats")
    if isinstance(stats, dict):
        if "Ions" in stats:
            stats["Ions"] = clamped
            return
        if "ions" in stats:
            stats["ions"] = clamped
            return
    player["Ions"] = clamped


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


def _convert_value(item_id: str, catalog: Any) -> int:
    meta = _resolve_meta(catalog, item_id)
    if not meta:
        return 0
    for key in ("convert_ions", "ion_value", "value"):
        if key in meta:
            try:
                return int(meta[key])
            except Exception:
                return 0
    return 0


def _choose_inventory_item(
    player: Dict[str, object],
    prefix: str,
    catalog: Any,
) -> Tuple[Optional[str], Optional[str]]:
    inventory: List[str] = list(player.get("inventory") or [])
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
        bus.push("SYSTEM/WARN", "You're not carrying a .")
        return {"ok": False, "reason": "missing_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    iid, item_id = _choose_inventory_item(player, prefix, catalog)
    if not iid or not item_id:
        bus.push("SYSTEM/WARN", f"You're not carrying a {prefix}.")
        return {"ok": False, "reason": "not_found"}

    value = _convert_value(item_id, catalog)

    inventory = list(player.get("inventory") or [])
    try:
        inventory.remove(iid)
    except ValueError:
        pass
    player["inventory"] = inventory

    itemsreg.delete_instance(iid)
    _set_ions(player, _get_ions(player) + value)
    itx._save_player(player)

    name = _display_name(item_id, catalog)
    bus.push("SYSTEM/OK", f"The {name} vanishes with a flash!")
    bus.push("SYSTEM/OK", f"You convert the {name} into {value} ions.")

    return {"ok": True, "iid": iid, "item_id": item_id, "ions": value}


def register(dispatch, ctx) -> None:
    dispatch.register("convert", lambda arg: convert_cmd(arg, ctx))
