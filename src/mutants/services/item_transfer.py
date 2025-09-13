from __future__ import annotations
import json, os, random, time
from typing import Dict, List, Optional
from ..io import atomic
from ..ui import item_display as idisp
from ..registries import items_instances as itemsreg

GROUND_CAP = 6
INV_CAP = 10  # worn armor excluded elsewhere


def _player_file() -> str:
    return os.path.join(os.getcwd(), "state", "playerlivestate.json")


def _load_player() -> Dict:
    try:
        return json.load(open(_player_file(), "r", encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _save_player(p: Dict) -> None:
    atomic.atomic_write_json(_player_file(), p)


def _ensure_inventory(p: Dict) -> None:
    if "inventory" not in p or not isinstance(p["inventory"], list):
        p["inventory"] = []


def _armor_iid(p: Dict) -> Optional[str]:
    a = p.get("armor")
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


def _inv_iids(p: Dict) -> List[str]:
    return list(p.get("inventory") or [])


def _pick_first_match_by_prefix(iids: List[str], prefix: str) -> Optional[str]:
    if not prefix:
        return None
    pref = prefix.strip().lower()
    for iid in iids:
        nm = _iid_to_name(iid).lower()
        if nm.startswith(pref):
            return iid
    return None


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
    p = _load_player()
    _ensure_inventory(p)
    year, x, y = _pos_from_ctx(ctx)
    ground_iids = _ground_ordered_ids(year, x, y)
    chosen_iid = None
    if prefix:
        chosen_iid = _pick_first_match_by_prefix(ground_iids, prefix)
    else:
        chosen_iid = ground_iids[0] if ground_iids else None
    if not chosen_iid:
        return {"ok": False, "reason": "not_found", "where": "ground"}
    itemsreg.clear_position(chosen_iid)
    inv = _inv_iids(p)
    inv.append(chosen_iid)
    p["inventory"] = inv
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
        p["inventory"] = inv
        overflow_info = {"inv_overflow_drop": drop_iid}
    _save_player(p)
    itemsreg.save_instances()
    return {"ok": True, "iid": chosen_iid, "overflow": overflow_info, "inv_count": len(p["inventory"])}


def drop_to_ground(ctx, prefix: str, *, seed: Optional[int] = None) -> Dict:
    p = _load_player()
    _ensure_inventory(p)
    inv = _inv_iids(p)
    if not inv:
        return {"ok": False, "reason": "inventory_empty"}
    iid = None
    if prefix:
        iid = _pick_first_match_by_prefix(inv, prefix)
    else:
        iid = inv[0]
    if not iid:
        return {"ok": False, "reason": "not_found", "where": "inventory"}
    if iid == _armor_iid(p):
        return {"ok": False, "reason": "armor_cannot_drop"}
    year, x, y = _pos_from_ctx(ctx)
    itemsreg.set_position(iid, year, x, y)
    inv = [i for i in inv if i != iid]
    p["inventory"] = inv
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, x, y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        inv.append(pick)
        p["inventory"] = inv
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, x, y)
            inv = [i for i in inv if i != drop_iid]
            p["inventory"] = inv
            overflow_info = {"ground_overflow_pick": pick, "inv_overflow_drop": drop_iid}
        else:
            overflow_info = {"ground_overflow_pick": pick}
    _save_player(p)
    itemsreg.save_instances()
    return {"ok": True, "iid": iid, "overflow": overflow_info, "inv_count": len(p["inventory"])}
