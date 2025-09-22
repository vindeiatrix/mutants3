from __future__ import annotations

from typing import Dict, Optional, Tuple

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import item_transfer as itx
from ..services import player_state as pstate
from ..services.equip_debug import _edbg_enabled, _edbg_log
from ..services.items_weight import effective_weight
from .convert import _choose_inventory_item, _display_name
from .wear import _bag_count, _catalog_template, _pos_repr


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


def wield_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    prefix = (arg or "").strip()
    if not prefix:
        if _edbg_enabled():
            try:
                state = pstate.load_state()
            except Exception:
                state = None
            cls_name = pstate.get_active_class(state) if state else None
            wield_iid = pstate.get_wielded_weapon_id(state) if state else None
            _edbg_log(
                "[ equip ] reject=missing_argument",
                cmd="wield",
                prefix=repr(prefix),
                **{
                    "class": cls_name or "None",
                    "pos": _pos_repr(state),
                    "bag_count": _bag_count(state=state),
                    "wield_iid": wield_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", "Usage: wield <item>")
        return {"ok": False, "reason": "missing_argument"}

    catalog = catreg.load_catalog() or {}
    player = itx._load_player()
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)

    stats_state = pstate.load_state()
    cls_name = pstate.get_active_class(stats_state)
    current_iid = pstate.get_wielded_weapon_id(stats_state)
    if _edbg_enabled():
        _edbg_log(
            "[ equip ] enter",
            cmd="wield",
            prefix=repr(prefix),
            **{
                "class": cls_name or "None",
                "pos": _pos_repr(stats_state, player),
                "bag_count": _bag_count(stats_state, player),
                "wield_iid": current_iid or "None",
            },
        )

    iid, item_id = _resolve_candidate(player, prefix, catalog)
    if not iid or not item_id:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=not_in_bag",
                cmd="wield",
                prefix=repr(prefix),
                **{
                    "class": cls_name or "None",
                    "bag_count": _bag_count(stats_state, player),
                    "wield_iid": current_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", f"You're not carrying a {prefix}.")
        return {"ok": False, "reason": "not_found"}

    inst = itemsreg.get_instance(iid) or {}
    template = _catalog_template(catalog, item_id)
    weight = max(0, effective_weight(inst, template))
    required = weight // 5
    name = _display_name(item_id, catalog)

    if _edbg_enabled():
        _edbg_log(
            "[ equip ] resolve ok",
            cmd="wield",
            prefix=repr(prefix),
            **{
                "iid": iid,
                "item_id": repr(item_id),
                "weight": weight,
                "required": required,
            },
        )

    stats = pstate.get_stats_for_active(stats_state)
    strength = _coerce_int(stats.get("str"), 0)
    gate_ok = strength >= required
    if _edbg_enabled():
        comp = ">=" if gate_ok else "<"
        outcome = "pass" if gate_ok else "fail"
        _edbg_log(
            f"[ equip ] gate strength={strength} {comp} required={required} weight={weight} -> {outcome}",
            cmd="wield",
            prefix=repr(prefix),
        )
    if not gate_ok:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=strength_gate",
                cmd="wield",
                prefix=repr(prefix),
                **{"strength": strength, "required": required, "weight": weight},
            )
        bus.push("SYSTEM/WARN", "You don't have the strength to wield that!")
        return {"ok": False, "reason": "insufficient_strength"}

    try:
        pstate.set_wielded_weapon(iid)
    except ValueError:
        if _edbg_enabled():
            _edbg_log(
                "[ equip ] reject=internal_error",
                cmd="wield",
                prefix=repr(prefix),
                **{"iid": iid, "item_id": repr(item_id)},
            )
        bus.push("SYSTEM/WARN", "You can't wield that.")
        return {"ok": False, "reason": "wield_failed"}

    bus.push("SYSTEM/OK", f"You wield the {name}.")

    result: Dict[str, object] = {
        "ok": True,
        "iid": iid,
        "item_id": item_id,
        "weight": weight,
        "required": required,
    }

    if _edbg_enabled():
        try:
            final_state = pstate.load_state()
        except Exception:
            final_state = None
        payload = {
            "cmd": "wield",
            "prefix": repr(prefix),
            "wielded_iid": iid,
            "item_id": repr(item_id),
            "bag_count": _bag_count(state=final_state),
            "weight": weight,
            "required": required,
        }
        if current_iid:
            payload["previous"] = current_iid
        _edbg_log("[ equip ] success=wield", **payload)

    return result


def register(dispatch, ctx) -> None:
    dispatch.register("wield", lambda arg: wield_cmd(arg, ctx))
    dispatch.alias("wie", "wield")
    dispatch.alias("wiel", "wield")
