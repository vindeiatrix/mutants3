from __future__ import annotations

from math import floor
from typing import Dict, Iterable, Optional, Tuple

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import player_state as pstate
from ..services import item_transfer as itx
from ..services.equip_debug import _edbg_enabled, _edbg_log
from ..services.items_weight import get_effective_weight
from .convert import _choose_inventory_item, _display_name


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _resolve_candidate(
    player: Dict[str, object],
    prefix: str,
    catalog: Dict[str, Dict[str, object]],
) -> Tuple[Optional[str], Optional[str]]:
    iid, item_id = _choose_inventory_item(player, prefix, catalog)
    if not iid or not item_id:
        return None, None

    inst = itemsreg.get_instance(iid) or {}
    candidate_item = (
        inst.get("item_id")
        or inst.get("catalog_id")
        or inst.get("id")
        or item_id
    )
    return str(iid), str(candidate_item)


def _is_armour(item_id: str, catalog: Dict[str, Dict[str, object]]) -> bool:
    if item_id == itemsreg.BROKEN_ARMOUR_ID:
        return True
    template = catalog.get(item_id)
    if not isinstance(template, dict):
        return False
    return bool(template.get("armour"))


def _inventory_items(payload: object) -> Iterable[str]:
    if isinstance(payload, dict):
        inventory = payload.get("inventory")
        if isinstance(inventory, list):
            return [str(item) for item in inventory if item]
    return []


def _bag_count(state: Optional[Dict[str, object]] = None, player: Optional[Dict[str, object]] = None) -> int:
    if player:
        items = list(_inventory_items(player))
        if items:
            return len(items)
    if state:
        active = state.get("active") if isinstance(state, dict) else None
        if isinstance(active, dict):
            items = list(_inventory_items(active))
            if items:
                return len(items)
        return len(list(_inventory_items(state)))
    return 0


def _pos_repr(state: Optional[Dict[str, object]] = None, player: Optional[Dict[str, object]] = None) -> str:
    candidate = None
    if isinstance(state, dict):
        active = state.get("active")
        if isinstance(active, dict):
            candidate = active.get("pos")
        if candidate is None:
            players = state.get("players")
            if isinstance(players, list):
                for entry in players:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("is_active"):
                        candidate = entry.get("pos")
                        break
                if candidate is None and players:
                    first = players[0]
                    if isinstance(first, dict):
                        candidate = first.get("pos")
        if candidate is None:
            candidate = state.get("pos")
    if candidate is None and isinstance(player, dict):
        candidate = player.get("pos")
    if isinstance(candidate, (list, tuple)):
        return "[" + ",".join(str(v) for v in candidate) + "]"
    if candidate is None:
        return "None"
    return str(candidate)


def _catalog_template(catalog: Dict[str, Dict[str, object]], item_id: str) -> Dict[str, object]:
    try:
        template = catalog.get(item_id)  # type: ignore[call-arg]
    except Exception:
        template = None
    if isinstance(template, dict):
        return template
    return {}


def wear_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    prefix = (arg or "").strip()
    if not prefix:
        if _edbg_enabled():
            try:
                state = pstate.load_state()
            except Exception:
                state = None
            cls_name = pstate.get_active_class(state) if state else None
            slot_iid = pstate.get_equipped_armour_id(state) if state else None
            _edbg_log(
                "[ equip ] reject=missing_argument",
                cmd="wear",
                prefix=repr(prefix),
                **{
                    "class": cls_name or "None",
                    "pos": _pos_repr(state),
                    "bag_count": _bag_count(state=state),
                    "slot_iid": slot_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", "Usage: wear <item>")
        return {"ok": False, "reason": "missing_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    stats_state = pstate.load_state()
    cls_name = pstate.get_active_class(stats_state)
    slot_iid = pstate.get_equipped_armour_id(stats_state)
    if _edbg_enabled():
        _edbg_log(
            "[ equip ] enter",
            cmd="wear",
            prefix=repr(prefix),
            **{
                "class": cls_name or "None",
                "pos": _pos_repr(stats_state, player),
                "bag_count": _bag_count(stats_state, player),
                "slot_iid": slot_iid or "None",
            },
        )

    iid, item_id = _resolve_candidate(player, prefix, catalog)
    if not iid or not item_id:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=not_in_bag",
                cmd="wear",
                prefix=repr(prefix),
                **{
                    "class": cls_name or "None",
                    "bag_count": _bag_count(stats_state, player),
                    "slot_iid": slot_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", f"You're not carrying a {prefix}.")
        return {"ok": False, "reason": "not_found"}

    template = _catalog_template(catalog, item_id)
    armour_flag = bool(template.get("armour"))
    armour_class = _coerce_int(template.get("armour_class"), 0)
    inst = itemsreg.get_instance(iid) or {}
    weight = max(0, get_effective_weight(inst, template))
    required = max(0, floor(weight / 10))
    broken = item_id == itemsreg.BROKEN_ARMOUR_ID or armour_class == 0
    if _edbg_enabled():
        _edbg_log(
            "[ equip ] resolve ok",
            cmd="wear",
            prefix=repr(prefix),
            **{
                "iid": iid,
                "item_id": repr(item_id),
                "armour": armour_flag,
                "weight": weight,
                "required": required,
                "ac": armour_class,
                "broken": broken,
            },
        )

    if not _is_armour(item_id, catalog):
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=not_armour",
                cmd="wear",
                prefix=repr(prefix),
                **{"iid": iid, "item_id": repr(item_id)},
            )
        bus.push("SYSTEM/WARN", "You can't wear that.")
        return {"ok": False, "reason": "not_armour"}

    stats = pstate.get_stats_for_active(stats_state)
    strength = _coerce_int(stats.get("str"), 0)
    monster_actor = itx.actor_is_monster(ctx)
    gate_ok = strength >= required
    if _edbg_enabled():
        comp = ">=" if gate_ok else "<"
        outcome = "pass" if gate_ok else "fail"
        _edbg_log(
            f"[ equip ] gate strength={strength} {comp} required={required} weight={weight} -> {outcome}",
        )
        if not gate_ok and monster_actor:
            _edbg_log(
                "[ equip ] gate bypass=monster",
                cmd="wear",
                prefix=repr(prefix),
                **{"strength": strength, "required": required, "weight": weight},
            )
    if not gate_ok and not monster_actor:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=strength_gate",
                cmd="wear",
                prefix=repr(prefix),
                **{"strength": strength, "required": required, "weight": weight},
            )
        bus.push("SYSTEM/WARN", "You don't have the strength to put that on!")
        return {"ok": False, "reason": "insufficient_strength"}

    current = slot_iid
    current_name: Optional[str] = None
    current_item_id: Optional[str] = None
    if current:
        current_inst = itemsreg.get_instance(current) or {}
        current_item_id = (
            current_inst.get("item_id")
            or current_inst.get("catalog_id")
            or current_inst.get("id")
            or current
        )
        current_name = _display_name(str(current_item_id), catalog)
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] slot occupied -> action=swap",
                cmd="wear",
                prefix=repr(prefix),
                **{
                    "old_iid": current,
                    "old_item_id": repr(str(current_item_id)),
                },
            )
    else:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] slot empty -> action=wear",
                cmd="wear",
                prefix=repr(prefix),
            )

    try:
        if current:
            pstate.unequip_armour()
        equipped = pstate.equip_armour(iid)
    except ValueError:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=internal_error",
                cmd="wear",
                prefix=repr(prefix),
                **{"iid": iid, "item_id": repr(item_id)},
            )
        bus.push("SYSTEM/WARN", "You can't wear that.")
        return {"ok": False, "reason": "equip_failed"}

    name = _display_name(item_id, catalog)
    if current and current_name:
        bus.push("SYSTEM/OK", f"You've removed the {current_name}.")
    bus.push("SYSTEM/OK", f"You've just put on the {name}.")

    result: Dict[str, object] = {"ok": True, "iid": equipped, "item_id": item_id}
    if current:
        result["swapped"] = current

    if _edbg_enabled():
        try:
            final_state = pstate.load_state()
        except Exception:
            final_state = None
        prev_template = (
            _catalog_template(catalog, str(current_item_id)) if current_item_id else {}
        )
        prev_ac = _coerce_int(prev_template.get("armour_class"), 0)
        ac_delta = armour_class - prev_ac
        payload = {
            "cmd": "wear",
            "prefix": repr(prefix),
            "equipped_iid": equipped,
            "item_id": repr(item_id),
            "bag_count": _bag_count(state=final_state),
            "ac_delta": f"{ac_delta:+d}",
        }
        if current:
            payload["old_to_bag"] = current
        msg = "[ equip ] success=swap" if current else "[ equip ] success=wear"
        _edbg_log(msg, **payload)

    return result


def register(dispatch, ctx) -> None:
    dispatch.register("wear", lambda arg: wear_cmd(arg, ctx))
    dispatch.alias("wea", "wear")
