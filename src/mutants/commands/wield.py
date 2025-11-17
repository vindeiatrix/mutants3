from __future__ import annotations

from typing import Dict, List, Mapping, MutableMapping, Optional, Tuple

from ..registries import items_catalog as catreg
from ..registries import items_instances as itemsreg
from ..services import item_transfer as itx
from ..services import player_state as pstate
from ..services import state_debug
from ..services.equip_debug import _edbg_enabled, _edbg_log
from ..services.items_weight import get_effective_weight
from ..util.textnorm import normalize_item_query
from .convert import _choose_inventory_item, _display_name
from .strike import strike_cmd
from ._helpers import resolve_ready_target_in_tile
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


def _state_from_ctx(ctx: Mapping[str, object] | MutableMapping[str, object]) -> Optional[Dict[str, object]]:
    if isinstance(ctx, MutableMapping):
        state = ctx.get("player_state")
        if isinstance(state, dict):
            return state
    try:
        state = pstate.load_state()
    except Exception:
        return None
    if isinstance(ctx, MutableMapping) and isinstance(state, dict):
        ctx["player_state"] = state
    return state if isinstance(state, dict) else None


def wield_cmd(arg: str, ctx: Dict[str, object]) -> Dict[str, object]:
    bus = ctx["feedback_bus"]
    prefix = (arg or "").strip()
    catalog = catreg.load_catalog() or {}
    player = pstate.ensure_player_state(ctx)
    pstate.ensure_active_profile(player, ctx)
    pstate.bind_inventory_to_active_class(player)
    itx._ensure_inventory(player)
    before_snapshot = state_debug.log_inventory_stage(
        ctx, player, command="wield", arg=prefix, stage="inventory_before"
    )

    if not prefix:
        if _edbg_enabled():
            state = _state_from_ctx(ctx)
            cls_name = pstate.get_active_class(state) if state else None
            wield_iid = pstate.get_wielded_weapon_id(state) if state else None
            _edbg_log(
                "[ equip ] reject=missing_argument",
                cmd="wield",
                prefix=repr(prefix),
                **{
                    "class": cls_name or "None",
                    "pos": _pos_repr(state, player),
                    "bag_count": _bag_count(state=state, player=player),
                    "wield_iid": wield_iid or "None",
                },
            )
        bus.push("SYSTEM/WARN", "Usage: wield <item>")
        return {"ok": False, "reason": "missing_argument"}

    stats_state = _state_from_ctx(ctx)
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
    if ready_target_id and not monster_actor:
        resolved_ready = resolve_ready_target_in_tile(ctx)
        if resolved_ready:
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
                        target=resolved_ready,
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
                        target=resolved_ready,
                        strike_ok=strike_summary.get("ok"),
                    )
    if strike_summary is not None:
        result["strike"] = strike_summary

    state_debug.log_inventory_update(
        ctx,
        player,
        command="wield",
        arg=prefix,
        before=before_snapshot,
        extra={"wielded_iid": iid, "previous": current_iid},
    )

    if _edbg_enabled():
        final_state = _state_from_ctx(ctx)
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
