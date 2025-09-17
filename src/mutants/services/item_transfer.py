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


def _load_state() -> Dict[str, Any]:
    """Load player state from disk with graceful fallbacks."""

    state = pstate.load_state()
    if isinstance(state, dict):
        return state
    return {}


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
    if "armour" in player and "armor" not in player:
        player["armor"] = player.pop("armour")
    inv = player.get("inventory")
    if isinstance(inv, list):
        cleaned = [i for i in inv if i]
    else:
        cleaned = []
    # Do NOT inherit from any top-level legacy 'inventory' when multi-player is present;
    # doing so would pollute per-player inventories after switching.
    player["inventory"] = cleaned
    return player


def _save_player(player: Dict[str, Any]) -> None:
    global _STATE_CACHE

    inv = [i for i in player.get("inventory", []) if i]
    state = _STATE_CACHE if isinstance(_STATE_CACHE, dict) else _load_state()
    players = state.get("players")
    if isinstance(players, list) and players:
        active_id = state.get("active_id")
        updated = False
        first_player = players[0]
        new_players: List[Dict[str, Any]] = []
        for existing in players:
            is_active = (active_id is not None and existing.get("id") == active_id) or (
                active_id is None and existing is first_player
            )
            if is_active:
                merged = {**existing, **player}
                merged["inventory"] = inv
                new_players.append(merged)
                updated = True
            else:
                new_players.append(existing)
        if not updated and player.get("id") is not None:
            new_players = []
            target_id = player.get("id")
            for existing in players:
                if existing.get("id") == target_id:
                    merged = {**existing, **player}
                    merged["inventory"] = inv
                    new_players.append(merged)
                    updated = True
                else:
                    new_players.append(existing)
        if not updated:
            merged = {**first_player, **player}
            merged["inventory"] = inv
            if new_players:
                new_players[0] = merged
            else:
                new_players.append(merged)
        state["players"] = new_players
    else:
        state.update(player)
        state.setdefault("players", [])
    player["inventory"] = inv
    # Do not maintain any top-level 'inventory' in state; inventories are per-player.
    pstate.save_state(state)
    _STATE_CACHE = None


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


def _ground_ordered_ids(year: int, x: int, y: int) -> List[str]:
    insts = itemsreg.list_instances_at(year, x, y)
    groups: Dict[str, List[Dict]] = {}
    order: List[str] = []
    for inst in insts:
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
    year, x, y = _pos_from_ctx(ctx)
    insts = itemsreg.list_instances_at(year, x, y)
    q = normalize_item_query(prefix)
    candidates: List[str] = []
    if q:
        for inst in insts:
            iid = inst.get("iid") or inst.get("instance_id")
            item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
            if not iid or not item_id:
                continue
            name = idisp.canonical_name(str(item_id))
            norm_name = normalize_item_query(name)
            norm_id = normalize_item_query(str(item_id))
            if norm_name.startswith(q) or norm_id.startswith(q):
                candidates.append(str(iid))
    else:
        for inst in insts:
            iid = inst.get("iid") or inst.get("instance_id")
            if iid:
                candidates.append(str(iid))
    chosen_iid: Optional[str] = candidates[0] if candidates else None
    if not chosen_iid:
        return {"ok": False, "reason": "not_found", "where": "ground"}
    itemsreg.clear_position(chosen_iid)
    inv = [i for i in player.get("inventory", []) if i]
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
            inv.append(swap_iid)
        itemsreg.set_position(drop_iid, year, x, y)
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
    inv = [i for i in player.get("inventory", []) if i]
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
    inv = [i for i in inv if i != iid]
    player["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, x, y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        inv.append(pick)
        player["inventory"] = inv
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, x, y)
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
    inv = [i for i in player.get("inventory", []) if i]
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
    inv = [i for i in inv if i != iid]
    player["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, drop_x, drop_y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        inv.append(pick)
        player["inventory"] = inv
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, drop_x, drop_y)
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
