from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from ..ui import item_display as idisp
from ..registries import items_instances as itemsreg
from ..util.textnorm import normalize_item_query
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.util.directions import vec as dir_vec
from mutants.services import player_state as pstate

_STATE_CACHE: Optional[Dict[str, Any]] = None

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"

GROUND_CAP = 6
INV_CAP = 10  # worn armor excluded elsewhere


# --- Inventory helpers (used by debug.py and services here) ---
def _ensure_inventory(p: Dict[str, Any]) -> None:
    """Normalize the inventory list stored on a player mapping."""

    inv = p.get("inventory")
    if not isinstance(inv, list):
        p["inventory"] = []
        return
    p["inventory"] = [i for i in inv if i]


def _load_state() -> Dict[str, Any]:
    """Load player state from disk with graceful fallbacks, and sanitize."""

    state = pstate.load_state()
    if not isinstance(state, dict):
        return {}

    sanitized = dict(state)
    legacy_inv = sanitized.get("inventory")
    if isinstance(legacy_inv, list):
        sanitized["_legacy_inventory"] = list(legacy_inv)
    # Never allow a stray top-level inventory to pollute per-player inventories.
    sanitized.pop("inventory", None)
    return sanitized


def _active_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the active player's mapping from a state payload."""

    players = state.get("players")
    if isinstance(players, list) and players:
        active_id = state.get("active_id")
        for player in players:
            if player.get("id") == active_id:
                return player
        return players[0]
    return state


def _load_player() -> Dict[str, Any]:
    global _STATE_CACHE

    state = _load_state()
    player = _active_from_state(state)
    _STATE_CACHE = state
    if not isinstance(player, dict):
        return {}
    inv = player.get("inventory")
    legacy = state.get("_legacy_inventory")
    if (not inv or not isinstance(inv, list)) and isinstance(legacy, list):
        player["inventory"] = list(legacy)
    if "armour" in player and "armor" not in player:
        player["armor"] = player.pop("armour")
    _ensure_inventory(player)
    return player


def _save_player(player: Dict[str, Any]) -> None:
    """Persist changes to the active player's record only."""

    global _STATE_CACHE

    _ensure_inventory(player)
    inv = list(player.get("inventory", []))

    def _apply(state: Dict[str, Any], active: Dict[str, Any]) -> None:
        active.update({k: v for k, v in player.items() if k != "inventory"})
        active["inventory"] = inv
        # Maintain a legacy top-level inventory mirror for tests/compatibility.
        state["inventory"] = list(inv)
        state["_legacy_inventory"] = list(inv)

    pstate.mutate_active(_apply)
    _STATE_CACHE = None


def scrub_instances(ctx: Optional[Dict[str, Any]] = None) -> int:
    """Strip ground coordinates from any instance held in a player's inventory."""

    state: Optional[Dict[str, Any]] = None
    if isinstance(ctx, dict):
        maybe_state = ctx.get("player_state")
        if isinstance(maybe_state, dict):
            state = maybe_state
    if state is None:
        state = _load_state()

    held: Dict[str, Optional[str]] = {}
    players = state.get("players") if isinstance(state, dict) else None
    if isinstance(players, list):
        for pl in players:
            if not isinstance(pl, dict):
                continue
            holder = pl.get("id")
            inv = pl.get("inventory")
            if not isinstance(inv, list):
                continue
            for entry in inv:
                iid: Optional[str] = None
                if isinstance(entry, str):
                    iid = entry
                elif isinstance(entry, dict):
                    for key in ("iid", "instance_id", "item_id"):
                        value = entry.get(key)
                        if value:
                            iid = str(value)
                            break
                if iid:
                    held[str(iid)] = str(holder) if holder else None

    try:
        return itemsreg.scrub_held_instances(held)
    except Exception:
        LOG.exception("[scrub] failed to sanitize held instances")
        return 0


def _armor_iid(p: Dict) -> Optional[str]:
    a = p.get("armor") or p.get("armour")
    if isinstance(a, dict):
        return a.get("iid") or a.get("instance_id")
    if isinstance(a, str):
        return a
    return None


def _iid_to_name(iid: str) -> str:
    inst = itemsreg.get_instance(iid)
    if not inst:
        return iid
    item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or iid
    return idisp.canonical_name(str(item_id))


def _norm_inst_tile(inst: Dict) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Normalize an instance's position to ints or None, tolerating legacy shapes."""

    pos = inst.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        year_val, x_val, y_val = pos[0], pos[1], pos[2]
    else:
        data = pos if isinstance(pos, dict) else {}
        year_val = data.get("year", inst.get("year"))
        x_val = data.get("x", inst.get("x"))
        y_val = data.get("y", inst.get("y"))

    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return (_to_int(year_val), _to_int(x_val), _to_int(y_val))


def _ground_ordered_ids(year: int, x: int, y: int) -> List[str]:
    # Authoritative id list for this tile
    ids = itemsreg.list_ids_at(year, x, y)
    groups: Dict[str, List[Dict]] = {}
    order: List[str] = []
    for iid in ids:
        inst = itemsreg.get_instance(iid) or {}
        item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        name = idisp.canonical_name(str(item_id)) if item_id else "Unknown"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(inst)
    out: List[str] = []
    for name in order:
        for i in groups[name]:
            iid = i.get("iid") or i.get("instance_id")
            if iid:
                out.append(str(iid))
    return out


def _pick_first_match_by_prefix(
    iids: List[str], prefix: str
) -> Tuple[Optional[str], Optional[List[str]]]:
    if not prefix:
        return (None, None)
    pref = prefix.strip().lower()
    matches: List[str] = []
    for iid in iids:
        nm = _iid_to_name(iid).lower()
        if nm.startswith(pref):
            matches.append(iid)
    if len(matches) == 1:
        return (matches[0], None)
    if len(matches) > 1:
        names = [_iid_to_name(i) for i in matches]
        # If all matched items share the same canonical name, treat as non-ambiguous.
        unique = {n.lower() for n in names}
        if len(unique) == 1:
            return (matches[0], None)
        # Otherwise surface candidate names to disambiguate.
        return (None, names)
    return (None, None)


def _rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed if seed is not None else time.time_ns())


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx["player_state"]
    aid = state.get("active_id")
    for pl in state.get("players", []):
        if pl.get("id") == aid:
            pos = pl.get("pos") or [0, 0, 0]
            return int(pos[0]), int(pos[1]), int(pos[2])
    pos = state.get("players", [{}])[0].get("pos") or [0, 0, 0]
    return int(pos[0]), int(pos[1]), int(pos[2])


def pick_from_ground(ctx, prefix: str, *, seed: Optional[int] = None) -> Dict:
    player = _load_player()
    _ensure_inventory(player)
    year, x, y = _pos_from_ctx(ctx)
    ids = itemsreg.list_ids_at(year, x, y)
    q = normalize_item_query(prefix)
    candidates: List[str] = []
    if q:
        for iid in ids:
            inst = itemsreg.get_instance(iid) or {}
            item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
            if not iid or not item_id:
                continue
            name = idisp.canonical_name(str(item_id))
            norm_name = normalize_item_query(name)
            norm_id = normalize_item_query(str(item_id))
            if norm_name.startswith(q) or norm_id.startswith(q):
                candidates.append(str(iid))
    else:
        for iid in ids:
            if iid:
                candidates.append(str(iid))
    chosen_iid: Optional[str] = candidates[0] if candidates else None
    if not chosen_iid:
        return {"ok": False, "reason": "not_found", "where": "ground"}
    # Safety: ensure the chosen instance is actually at our tile (fresh read, robust to None).
    inst = itemsreg.get_instance(chosen_iid) or {}
    inst_year, inst_x, inst_y = _norm_inst_tile(inst)
    if inst_year != int(year) or inst_x != int(x) or inst_y != int(y):
        # Refresh the candidate list from the authoritative store and retry once.
        ids = itemsreg.list_ids_at(year, x, y)
        candidates = []
        if q:
            for iid in ids:
                inst = itemsreg.get_instance(iid) or {}
                item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
                if not iid or not item_id:
                    continue
                name = idisp.canonical_name(str(item_id))
                norm_name = normalize_item_query(name)
                norm_id = normalize_item_query(str(item_id))
                if norm_name.startswith(q) or norm_id.startswith(q):
                    candidates.append(str(iid))
        else:
            for iid in ids:
                if iid:
                    candidates.append(str(iid))
        chosen_iid = candidates[0] if candidates else None
        if not chosen_iid:
            return {"ok": False, "reason": "not_found", "where": "ground"}
    itemsreg.clear_position(chosen_iid)
    itemsreg.set_held_by(chosen_iid, player.get("id"))
    inv = list(player.get("inventory", []))
    inv.append(chosen_iid)
    player["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    if len(inv) > INV_CAP:
        drop_iid = rng.choice(inv)
        ground_now = _ground_ordered_ids(year, x, y)
        if len(ground_now) >= GROUND_CAP:
            swap_iid = rng.choice(ground_now)
            itemsreg.clear_position(swap_iid)
            itemsreg.set_held_by(swap_iid, player.get("id"))
            inv.append(swap_iid)
        itemsreg.set_position(drop_iid, year, x, y)
        itemsreg.set_held_by(drop_iid, None)
        inv = [i for i in inv if i != drop_iid]
        player["inventory"] = inv
        overflow_info = {"inv_overflow_drop": drop_iid}
    _save_player(player)
    itemsreg.save_instances()
    return {
        "ok": True,
        "iid": chosen_iid,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
    }


def drop_to_ground(ctx, prefix: str, *, seed: Optional[int] = None) -> Dict:
    player = _load_player()
    _ensure_inventory(player)
    inv = list(player.get("inventory", []))
    if not inv:
        return {"ok": False, "reason": "inventory_empty"}
    iid: Optional[str] = None
    if prefix:
        q = normalize_item_query(prefix)
        if q:
            # FIRST MATCH WINS (preserve inventory order) — same as THROW
            for cand in inv:
                inst = itemsreg.get_instance(cand) or {}
                item_id = (
                    inst.get("item_id")
                    or inst.get("catalog_id")
                    or inst.get("id")
                    or cand
                )
                name = idisp.canonical_name(str(item_id))
                norm_name = normalize_item_query(name)
                norm_id = normalize_item_query(str(item_id))
                if norm_name.startswith(q) or norm_id.startswith(q):
                    iid = cand
                    break
    else:
        iid = inv[0]
    if not iid:
        return {"ok": False, "reason": "not_found", "where": "inventory"}
    if iid == _armor_iid(player):
        return {"ok": False, "reason": "armor_cannot_drop"}
    year, x, y = _pos_from_ctx(ctx)
    itemsreg.set_position(iid, year, x, y)
    itemsreg.set_held_by(iid, None)
    inv = [i for i in inv if i != iid]
    player["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, x, y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        itemsreg.set_held_by(pick, player.get("id"))
        inv.append(pick)
        player["inventory"] = inv
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, x, y)
            itemsreg.set_held_by(drop_iid, None)
            inv = [i for i in inv if i != drop_iid]
            player["inventory"] = inv
            overflow_info = {"ground_overflow_pick": pick, "inv_overflow_drop": drop_iid}
        else:
            overflow_info = {"ground_overflow_pick": pick}
    _save_player(player)
    itemsreg.save_instances()
    return {
        "ok": True,
        "iid": iid,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
    }


def throw_to_direction(ctx, direction: str, prefix: str, *, seed: Optional[int] = None) -> Dict:
    player = _load_player()
    _ensure_inventory(player)
    inv = list(player.get("inventory", []))
    if not inv:
        return {"ok": False, "reason": "inventory_empty"}
    iid: Optional[str] = None
    if prefix:
        q = normalize_item_query(prefix)
        if q:
            for cand in inv:  # preserve inventory order
                inst = itemsreg.get_instance(cand) or {}
                item_id = (
                    inst.get("item_id")
                    or inst.get("catalog_id")
                    or inst.get("id")
                    or cand
                )
                name = idisp.canonical_name(str(item_id))
                norm_name = normalize_item_query(name)
                norm_id = normalize_item_query(str(item_id))
                if norm_name.startswith(q) or norm_id.startswith(q):
                    iid = cand
                    break
    else:
        iid = inv[0]
    if not iid:
        return {"ok": False, "reason": "not_found", "where": "inventory"}
    if iid == _armor_iid(player):
        return {"ok": False, "reason": "armor_cannot_drop"}
    year, x, y = _pos_from_ctx(ctx)
    world = ctx["world_loader"](year)
    dir_code = direction[:1].upper()
    dec = ER.resolve(world, dyn, year, x, y, dir_code, actor={})
    dx, dy = dir_vec(direction)
    tx, ty = x + dx, y + dy
    if dec.passable:
        drop_x, drop_y = tx, ty
        blocked = False
    else:
        drop_x, drop_y = x, y
        blocked = True
        if WORLD_DEBUG:
            cur = dec.cur_raw or {}
            nbr = dec.nbr_raw or {}
            LOG.debug(
                "[throw] blocked (%s,%s,%s)->%s reason=%s cur(base=%s,gs=%s) nbr(base=%s,gs=%s)",
                year,
                x,
                y,
                dir_code,
                getattr(dec, "reason", "blocked"),
                cur.get("base"),
                cur.get("gate_state"),
                nbr.get("base"),
                nbr.get("gate_state"),
            )
    itemsreg.set_position(iid, year, drop_x, drop_y)
    itemsreg.set_held_by(iid, None)
    inv = [i for i in inv if i != iid]
    player["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, drop_x, drop_y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        itemsreg.set_held_by(pick, player.get("id"))
        inv.append(pick)
        player["inventory"] = inv
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, drop_x, drop_y)
            itemsreg.set_held_by(drop_iid, None)
            inv = [i for i in inv if i != drop_iid]
            player["inventory"] = inv
            overflow_info = {"ground_overflow_pick": pick, "inv_overflow_drop": drop_iid}
        else:
            overflow_info = {"ground_overflow_pick": pick}
    _save_player(player)
    itemsreg.save_instances()
    return {
        "ok": True,
        "iid": iid,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
        "blocked": blocked,
    }
