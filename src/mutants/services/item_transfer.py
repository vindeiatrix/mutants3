from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple
from ..ui import item_display as idisp
from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..debug import items_probe
from ..util.textnorm import normalize_item_query
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.util.directions import vec as dir_vec
from mutants.services import player_state as pstate
from mutants.services import state_debug
from ..services.items_weight import get_effective_weight

LOG = logging.getLogger(__name__)
ITEMS_LOG = logging.getLogger("mutants.itemsdbg")
LOG_P = logging.getLogger("mutants.playersdbg")
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"


def _pdbg_enabled() -> bool:
    return bool(os.environ.get("PLAYERS_DEBUG"))

GROUND_CAP = 6
INV_CAP = 10  # worn armor excluded elsewhere


# --- Value coercion helpers ---
def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


# --- Inventory helpers (used by debug.py and services here) ---
def _ensure_inventory(p: Dict[str, Any]) -> None:
    """Normalize the inventory list stored on a player mapping."""

    inv = p.get("inventory")
    if not isinstance(inv, list):
        normalized: List[str] = []
    else:
        normalized = [str(i) for i in inv if i]

    p["inventory"] = normalized

    active = p.get("active")
    if isinstance(active, dict):
        active["inventory"] = normalized
        klass = active.get("class") or p.get("class")
    else:
        klass = p.get("class")

    if klass is not None:
        klass_str = str(klass)
        bags = p.get("bags")
        if isinstance(bags, dict):
            bags[klass_str] = normalized


def _state_from_ctx(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the player state associated with ``ctx``."""

    if isinstance(ctx, MutableMapping):
        existing = ctx.get("player_state")
        if isinstance(existing, dict):
            return existing
        state = pstate.load_state()
        ctx["player_state"] = state
        return state
    state = pstate.load_state()
    return state if isinstance(state, dict) else {}
def _mark_player_dirty(player: MutableMapping[str, Any]) -> None:
    try:
        player["_dirty"] = True
    except Exception:  # pragma: no cover - defensive
        pass


def _save_player(ctx: Mapping[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    """Update the player state stored in ``ctx`` after a mutation."""

    state = _state_from_ctx(ctx)

    _ensure_inventory(player)
    inv = list(player.get("inventory", []))

    players = state.get("players")
    active_id = state.get("active_id")
    active_entry: Dict[str, Any] = player

    if isinstance(players, list) and players:
        for idx, existing in enumerate(players):
            if not isinstance(existing, MutableMapping):
                continue
            is_active = False
            if active_id is not None:
                is_active = existing.get("id") == active_id
            else:
                is_active = idx == 0
            if is_active:
                if existing is not player:
                    existing.update(player)
                active_entry = existing
                break
        else:
            active_entry = {**player}
            players.append(active_entry)
    else:
        state.update(player)
        active_entry = state
        state.setdefault("players", [active_entry])

    active_entry["inventory"] = list(inv)
    state["inventory"] = list(inv)

    klass_raw = active_entry.get("class") or active_entry.get("name")
    if not klass_raw:
        active_profile = state.get("active")
        if isinstance(active_profile, Mapping):
            klass_raw = active_profile.get("class") or active_profile.get("name")

    if isinstance(klass_raw, str) and klass_raw:
        klass = klass_raw
        bags = state.get("bags")
        if not isinstance(bags, dict):
            bags = {}
        bags[klass] = list(inv)
        state["bags"] = bags

        active_profile = state.get("active")
        if not isinstance(active_profile, MutableMapping):
            active_profile = {}
        active_profile.update(active_entry)
        if not isinstance(active_profile.get("bags"), dict):
            active_profile["bags"] = {}
        active_profile["bags"][klass] = list(inv)
        active_profile["inventory"] = list(inv)
        state["active"] = active_profile
    else:
        state["active"] = active_entry

    _mark_player_dirty(active_entry)
    if player is not active_entry and isinstance(player, MutableMapping):
        _mark_player_dirty(player)

    if isinstance(ctx, MutableMapping):
        ctx["player_state"] = state
        ctx["_runtime_player"] = active_entry

        # Persist immediately so subsequent commands that reload the state
        # (e.g., ``stat``) observe the inventory mutation. Without this, a
        # dropped item could linger in the canonical inventory view even
        # though the runtime cache was updated.
        pstate.save_player_state(ctx)

    return active_entry


def _armor_iid(p: Dict) -> Optional[str]:
    equipped = pstate.get_equipped_armour_id(p)
    if equipped:
        return equipped
    a = p.get("armor") or p.get("armour")
    if isinstance(a, dict):
        candidate = (
            a.get("iid")
            or a.get("instance_id")
            or a.get("wearing")
            or a.get("armour")
            or a.get("armor")
        )
        return str(candidate) if candidate else None
    if isinstance(a, str):
        return a
    return None


def _iid_to_name(iid: str) -> str:
    inst = itemsreg.get_instance(iid)
    if not inst:
        return iid
    item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or iid
    return idisp.canonical_name(str(item_id))


def _display_name_for(item_id: str) -> str:
    cat = catreg.load_catalog() or {}
    base = cat.get(str(item_id)) if cat else None
    if isinstance(base, dict):
        return str(base.get("display") or base.get("name") or item_id)
    return idisp.canonical_name(str(item_id))


def _choose_instance_from_prefix(
    insts: List[Dict[str, Any]], prefix: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Pick an instance from ``insts`` matching ``prefix``.

    Returns ``(instance, None)`` on success. On failure, returns ``(None, info)``
    where ``info`` includes at least a ``reason`` key and may provide
    ``message`` and ``candidates`` for UI hints.
    """

    q = normalize_item_query(prefix)
    if not insts:
        return None, {"reason": "not_found", "message": "There are no items here."}

    candidates: List[Tuple[str, str, Dict[str, Any]]] = []
    for inst in insts:
        item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
        if not item_id:
            continue
        name = _display_name_for(str(item_id))
        candidates.append((str(item_id), name, inst))

    if not candidates:
        return None, {"reason": "not_found", "message": "There are no items here."}

    if not q:
        # No prefix supplied – return the first candidate to preserve legacy behaviour.
        return candidates[0][2], None

    qq = q.lower()
    filtered: List[Tuple[str, str, Dict[str, Any]]] = []
    for item_id, name, inst in candidates:
        norm_name = normalize_item_query(name)
        if item_id.lower().startswith(qq) or norm_name.startswith(q):
            filtered.append((item_id, name, inst))

    if not filtered:
        tips = [name for _, name, _ in candidates[:5]]
        info: Dict[str, Any] = {
            "reason": "not_found",
            "message": f"No item here matches “{prefix}”.",
        }
        if tips:
            info["candidates"] = tips
        return None, info

    for item_id, name, inst in filtered:
        if item_id.lower() == qq or normalize_item_query(name) == q:
            return inst, None

    return filtered[0][2], None


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


def _remove_first(seq: List[str], target: str) -> List[str]:
    """Return *seq* without the first occurrence of *target* (if present)."""

    remaining = list(seq)
    try:
        remaining.remove(target)
    except ValueError:
        return remaining
    return remaining


def _rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed if seed is not None else time.time_ns())


def _pos_from_ctx(ctx) -> tuple[int, int, int]:
    state = ctx.get("player_state") if isinstance(ctx, Mapping) else None
    return pstate.canonical_player_pos(state)


def pick_from_ground(ctx, prefix: str, *, seed: Optional[int] = None) -> Dict:
    state = _state_from_ctx(ctx)
    state, player = pstate.get_active_pair(state)
    active_class = player.get("class") or pstate.get_active_class(state)
    if isinstance(ctx, MutableMapping):
        ctx["player_state"] = state
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    _ensure_inventory(player)
    before_snapshot = state_debug.log_inventory_stage(
        ctx, player, command="get", arg=prefix, stage="inventory_before"
    )
    year, x, y = _pos_from_ctx(ctx)
    # Command-side probe (before filtering/mutation)
    try:
        items_probe.probe("command-pre", itemsreg, year, x, y)
    except Exception:
        pass

    insts = itemsreg.list_instances_at(year, x, y)
    catalog = catreg.load_catalog() or {}
    if _pdbg_enabled():
        try:
            before_inv = list(player.get("inventory") or [])
            LOG_P.info(
                "[playersdbg] PICKUP-BEFORE class=%s pos=%s inv_iids=%s tile=(%s,%s,%s) tile_items=%s",
                player.get("active", {}).get("class") or player.get("class"),
                pstate.canonical_player_pos(player),
                before_inv,
                year,
                x,
                y,
                [inst.get("item_id") for inst in insts],
            )
        except Exception:  # pragma: no cover - defensive logging only
            pass
    if items_probe.enabled():
        try:
            items_probe.setup_file_logging()
            items_probe.dump_tile_instances(itemsreg, year, x, y, tag="command-pre")
            items_probe.find_all(itemsreg, "light_spear")
        except Exception:
            pass
    chosen_inst, failure = _choose_instance_from_prefix(insts, prefix)
    if failure:
        decision = {"ok": False, "where": "ground"}
        decision["reason"] = failure.get("reason", "not_found")
        if failure.get("message"):
            decision["message"] = failure["message"]
        if failure.get("candidates"):
            decision["candidates"] = list(failure["candidates"])
        if items_probe.enabled():
            ITEMS_LOG.error(
                "[itemsdbg] PICKUP no-match prefix=%r at year=%s x=%s y=%s",
                prefix,
                year,
                x,
                y,
            )
        return decision

    assert chosen_inst is not None
    chosen_iid = chosen_inst.get("iid") or chosen_inst.get("instance_id")
    if not chosen_iid:
        return {"ok": False, "reason": "not_found", "where": "ground"}

    chosen_iid = str(chosen_iid)
    item_id = (
        chosen_inst.get("item_id")
        or chosen_inst.get("catalog_id")
        or chosen_inst.get("id")
        or chosen_iid
    )
    display_name = _display_name_for(str(item_id)) if item_id else _iid_to_name(chosen_iid)
    if items_probe.enabled():
        ITEMS_LOG.info(
            "[itemsdbg] PICKUP choose iid=%s item_id=%s display=%s from_tile=(%s,%s,%s)",
            chosen_iid,
            item_id,
            display_name,
            year,
            x,
            y,
        )
    if not any(
        str(p.get("iid") or p.get("instance_id")) == chosen_iid for p in insts
    ):
        ITEMS_LOG.error(
            "[itemsdbg] PICKUP abort — iid=%s missing from tile snapshot (%s,%s,%s). insts=%s",
            chosen_iid,
            year,
            x,
            y,
            [str(p.get("iid") or p.get("instance_id")) for p in insts],
        )
        return {
            "ok": False,
            "reason": "not_found",
            "where": "ground",
            "message": "No such item on the ground here.",
        }

    template = catalog.get(str(item_id)) if item_id else None
    template_map = template if isinstance(template, dict) else None
    weight = max(0, get_effective_weight(chosen_inst, template_map))
    required = weight // 10
    state_for_stats = _state_from_ctx(ctx)
    stats = pstate.get_stats_for_active(state_for_stats)
    strength = _coerce_int(stats.get("str"), 0)
    monster_actor = actor_is_monster(ctx)
    if strength < required and not monster_actor:
        return {
            "ok": False,
            "reason": "insufficient_strength",
            "where": "ground",
            "message": "You don't have enough strength to pick that up!",
            "required": required,
            "weight": weight,
        }
    if strength < required and monster_actor and _pdbg_enabled():
        try:
            LOG_P.info(
                "[playersdbg] PICKUP bypass=strength_gate actor=monster strength=%s required=%s weight=%s",
                strength,
                required,
                weight,
            )
        except Exception:  # pragma: no cover - defensive logging only
            pass

    ok = itemsreg.clear_position_at(chosen_iid, year, x, y)
    if not ok:
        return {"ok": False, "reason": "That item is no longer on the ground here."}
    if isinstance(chosen_inst, MutableMapping):
        chosen_inst["origin"] = "world"
    actual_inst = itemsreg.get_instance(chosen_iid)
    if isinstance(actual_inst, MutableMapping):
        actual_inst["origin"] = "world"

    owner_payload = {"kind": "player", "id": player.get("id")}
    try:
        itemsreg.update_instance(
            chosen_iid,
            year=-1,
            x=-1,
            y=-1,
            owner=json.dumps(owner_payload, sort_keys=True),
        )
    except KeyError:
        return {"ok": False, "reason": "That item is no longer available."}

    pstate.add_item_to_active_inventory(state, player, chosen_iid)
    inv = list(state.get("bags", {}).get(active_class, player.get("inventory", [])) or [])

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
        inv = _remove_first(inv, drop_iid)
        overflow_info = {"inv_overflow_drop": drop_iid}

    inv = pstate.update_player_inventory(state, active_class, inv)
    player["inventory"] = list(inv)
    _mark_player_dirty(player)

    if isinstance(ctx, MutableMapping):
        ctx["player_state"] = state
        ctx["_runtime_player"] = player

    _save_player(ctx, player)
    state_debug.log_inventory_update(
        ctx,
        player,
        command="get",
        arg=prefix,
        before=before_snapshot,
        extra={"picked_iid": chosen_iid, "overflow": overflow_info},
    )
    if _pdbg_enabled():
        try:
            after_inv = list(player.get("inventory") or [])
            LOG_P.info(
                "[playersdbg] PICKUP-AFTER class=%s added_iid=%s inv_iids=%s",
                player.get("active", {}).get("class") or player.get("class"),
                chosen_iid,
                after_inv,
            )
        except Exception:  # pragma: no cover - defensive logging only
            pass
    # Command-side probe (after mutation & save)
    try:
        items_probe.probe("command-post", itemsreg, year, x, y)
    except Exception:
        pass

    _post = itemsreg.list_instances_at(year, x, y)
    if any(str(p.get("iid") or p.get("instance_id")) == chosen_iid for p in _post):
        ITEMS_LOG.error(
            "[itemsdbg] PICKUP consistency — iid=%s still present after save; forcing clear",
            chosen_iid,
        )
        itemsreg.clear_position(chosen_iid)
        _post_retry = itemsreg.list_instances_at(year, x, y)
        if any(
            str(p.get("iid") or p.get("instance_id")) == chosen_iid for p in _post_retry
        ):
            ITEMS_LOG.error(
                "[itemsdbg] PICKUP hard fail — iid=%s persists on tile after force clear",
                chosen_iid,
            )

    if items_probe.enabled():
        try:
            items_probe.dump_tile_instances(itemsreg, year, x, y, tag="command-post")
            items_probe.find_all(itemsreg, "light_spear")
        except Exception:
            pass

    return {
        "ok": True,
        "iid": chosen_iid,
        "item_id": str(item_id) if item_id else None,
        "display_name": display_name,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
    }


def drop_to_ground(ctx, prefix: str, *, seed: Optional[int] = None) -> Dict:
    player = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    _ensure_inventory(player)
    before_snapshot = state_debug.log_inventory_stage(
        ctx, player, command="drop", arg=prefix, stage="inventory_before"
    )
    inv = list(player.get("inventory", []))
    equipped = _armor_iid(player)
    if not inv:
        if not prefix and equipped:
            return {"ok": False, "reason": "armor_cannot_drop"}
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
        if prefix and equipped:
            q = normalize_item_query(prefix)
            if q:
                inst = itemsreg.get_instance(equipped) or {}
                item_id = (
                    inst.get("item_id")
                    or inst.get("catalog_id")
                    or inst.get("id")
                    or equipped
                )
                name = idisp.canonical_name(str(item_id))
                norm_name = normalize_item_query(name)
                norm_id = normalize_item_query(str(item_id))
                if norm_name.startswith(q) or norm_id.startswith(q):
                    return {"ok": False, "reason": "armor_cannot_drop"}
        return {"ok": False, "reason": "not_found", "where": "inventory"}
    if iid == _armor_iid(player):
        return {"ok": False, "reason": "armor_cannot_drop"}
    year, x, y = _pos_from_ctx(ctx)
    itemsreg.set_position(iid, year, x, y)
    inv = _remove_first(inv, iid)
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
            inv = _remove_first(inv, drop_iid)
            player["inventory"] = inv
            overflow_info = {"ground_overflow_pick": pick, "inv_overflow_drop": drop_iid}
        else:
            overflow_info = {"ground_overflow_pick": pick}
    _save_player(ctx, player)
    state_debug.log_inventory_update(
        ctx,
        player,
        command="drop",
        arg=prefix,
        before=before_snapshot,
        extra={"dropped_iid": iid, "overflow": overflow_info},
    )
    return {
        "ok": True,
        "iid": iid,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
    }


def throw_to_direction(ctx, direction: str, prefix: str, *, seed: Optional[int] = None) -> Dict:
    player = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    _ensure_inventory(player)
    before_snapshot = state_debug.log_inventory_stage(
        ctx,
        player,
        command="throw",
        arg=f"{direction}:{prefix}",
        stage="inventory_before",
    )
    inv = list(player.get("inventory", []))
    equipped = _armor_iid(player)
    if not inv:
        if not prefix and equipped:
            return {"ok": False, "reason": "armor_cannot_drop"}
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
        if prefix and equipped:
            q = normalize_item_query(prefix)
            if q:
                inst = itemsreg.get_instance(equipped) or {}
                item_id = (
                    inst.get("item_id")
                    or inst.get("catalog_id")
                    or inst.get("id")
                    or equipped
                )
                name = idisp.canonical_name(str(item_id))
                norm_name = normalize_item_query(name)
                norm_id = normalize_item_query(str(item_id))
                if norm_name.startswith(q) or norm_id.startswith(q):
                    return {"ok": False, "reason": "armor_cannot_drop"}
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
    inv = _remove_first(inv, iid)
    player["inventory"] = inv
    _mark_player_dirty(player)
    overflow_info = None
    rng = _rng(seed)
    ground_after = _ground_ordered_ids(year, drop_x, drop_y)
    if len(ground_after) > GROUND_CAP:
        candidates = [g for g in ground_after if g != iid] or ground_after
        pick = rng.choice(candidates)
        itemsreg.clear_position(pick)
        inv.append(pick)
        player["inventory"] = inv
        _mark_player_dirty(player)
        if len(inv) > INV_CAP:
            drop_iid = rng.choice(inv)
            itemsreg.set_position(drop_iid, year, drop_x, drop_y)
            inv = _remove_first(inv, drop_iid)
            player["inventory"] = inv
            _mark_player_dirty(player)
            overflow_info = {"ground_overflow_pick": pick, "inv_overflow_drop": drop_iid}
        else:
            overflow_info = {"ground_overflow_pick": pick}
    _save_player(ctx, player)
    state_debug.log_inventory_update(
        ctx,
        player,
        command="throw",
        arg=f"{direction}:{prefix}",
        before=before_snapshot,
        extra={
            "thrown_iid": iid,
            "overflow": overflow_info,
            "blocked": blocked,
        },
    )
    return {
        "ok": True,
        "iid": iid,
        "overflow": overflow_info,
        "inv_count": len(player.get("inventory", [])),
        "blocked": blocked,
    }


def _coerce_str(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    try:
        return str(value) if value else None
    except Exception:
        return None


def actor_is_monster(ctx: Mapping[str, Any] | None) -> bool:
    """Return ``True`` when the acting entity should bypass strength gates."""

    if not isinstance(ctx, Mapping):
        return False

    actor = ctx.get("actor")
    if isinstance(actor, Mapping):
        for key in ("kind", "type", "actor_kind"):
            raw = _coerce_str(actor.get(key))
            if raw and raw.lower() == "monster":
                return True
        if actor.get("is_monster"):
            return True

    raw_kind = _coerce_str(ctx.get("actor_kind"))
    if raw_kind and raw_kind.lower() == "monster":
        return True

    if ctx.get("is_monster"):
        return True

    return False


