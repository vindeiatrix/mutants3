from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import player_state as pstate
from ..services.equip_debug import _edbg_enabled, _edbg_log
from ..services.items_weight import get_effective_weight
from ..util.textnorm import normalize_item_query
from .convert import _choose_inventory_item, _display_name
from .strike import strike_cmd
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
        inventory: List[str] = [str(i) for i in (player.get("inventory") or []) if i]
        query = normalize_item_query(prefix).lower()
        if not query:
            return None, None
        for candidate in inventory:
            inst = itemsreg.get_instance(candidate)
            if not inst:
                continue
            item_id = (
                inst.get("item_id")
                or inst.get("catalog_id")
                or inst.get("id")
                or candidate
            )
            label = _display_name(str(item_id), catalog).lower()
            if str(item_id).lower().startswith(query) or label.startswith(query):
                return str(candidate), str(item_id)
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
    from ..services import item_transfer as itx

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
    ready_target_id = (
        pstate.get_ready_target_for_active(stats_state)
        if isinstance(stats_state, dict)
        else None
    )
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
    weight = max(0, get_effective_weight(inst, template))
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
    monster_actor = itx.actor_is_monster(ctx)
    gate_ok = strength >= required
    if _edbg_enabled():
        comp = ">=" if gate_ok else "<"
        outcome = "pass" if gate_ok else "fail"
        _edbg_log(
            f"[ equip ] gate strength={strength} {comp} required={required} weight={weight} -> {outcome}",
            cmd="wield",
            prefix=repr(prefix),
        )
        if not gate_ok and monster_actor:
            _edbg_log(
                "[ equip ] gate bypass=monster",
                cmd="wield",
                prefix=repr(prefix),
                **{"strength": strength, "required": required, "weight": weight},
            )
    if not gate_ok and not monster_actor:
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

    strike_summary: Optional[Dict[str, object]] = None
    if not monster_actor:
        try:
            strike_result = strike_cmd("", ctx)
        except Exception as exc:  # pragma: no cover - defensive guard
            strike_summary = {
                "ok": False,
                "reason": "auto_strike_failed",
                "error": str(exc),
            }
            if _edbg_enabled():
                _edbg_log(
                    "[ equip ] auto_strike failure",
                    cmd="wield",
                    prefix=repr(prefix),
                    target=ready_target_id or "None",
                    error=str(exc),
                )
        else:
            if isinstance(strike_result, dict):
                strike_summary = dict(strike_result)
            else:
                strike_summary = {"ok": False, "reason": "auto_strike_invalid"}
            if _edbg_enabled():
                _edbg_log(
                    "[ equip ] auto_strike",
                    cmd="wield",
                    prefix=repr(prefix),
                    target=ready_target_id or "None",
                    strike_ok=strike_summary.get("ok") if isinstance(strike_summary, dict) else None,
                )
    if strike_summary is not None:
        result["strike"] = strike_summary
        if (
            isinstance(strike_summary, dict)
            and strike_summary.get("ok")
            and strike_summary.get("damage", 0) > 0
        ):
            target_id = strike_summary.get("target_id") or ready_target_id
            monsters_obj = ctx.get("monsters") if isinstance(ctx, Mapping) else None
            target = None
            if target_id and monsters_obj is not None:
                getter = getattr(monsters_obj, "get", None)
                if callable(getter):
                    try:
                        target = getter(target_id)
                    except Exception:
                        target = None
            if target is not None:
                try:
                    from ..services import damage_engine as _damage_engine

                    _damage_engine.wake_target_if_asleep(ctx, target)
                except Exception:
                    pass

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
