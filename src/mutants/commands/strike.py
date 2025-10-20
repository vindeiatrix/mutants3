from __future__ import annotations

MIN_INNATE_DAMAGE = 6
MIN_BOLT_DAMAGE = 6

import logging
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.registries.monsters_catalog import exp_for as monster_exp_for, load_monsters_catalog
from mutants.services import combat_loot
from mutants.services import damage_engine, items_wear, monsters_state, player_state as pstate
from mutants.debug import turnlog
from mutants.ui.item_display import item_label, with_article


LOG = logging.getLogger(__name__)


def _load_monsters(ctx: Mapping[str, Any]) -> Any:
    monsters = ctx.get("monsters")
    if monsters is not None:
        return monsters
    try:
        state = monsters_state.load_state()
    except Exception:
        return None
    if isinstance(ctx, MutableMapping):
        ctx["monsters"] = state  # type: ignore[index]
    return state


def _monster_display_name(monster: Mapping[str, Any], fallback: str) -> str:
    name = monster.get("name") or monster.get("monster_id")
    return str(name) if name else fallback


def _sanitize_hp(monster: Mapping[str, Any]) -> tuple[int, int]:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        try:
            current = int(hp_block.get("current", 0))
        except (TypeError, ValueError):
            current = 0
        try:
            maximum = int(hp_block.get("max", current))
        except (TypeError, ValueError):
            maximum = current
        return max(0, current), max(0, maximum)
    return 0, 0


def _is_alive(monster: Mapping[str, Any]) -> bool:
    current, _ = _sanitize_hp(monster)
    return current > 0


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_pos(value: Any, fallback: Optional[Sequence[int]] = None) -> Optional[tuple[int, int, int]]:
    pos = combat_loot.coerce_pos(value)
    if pos is not None:
        return pos
    if fallback is None:
        return None
    return combat_loot.coerce_pos(fallback)


def _resolve_target_armour(monster: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    armour = monster.get("armour_slot")
    if isinstance(armour, MutableMapping):
        return armour
    return None


def _apply_weapon_wear(
    weapon_iid: Optional[str],
    wear_amount: int,
    catalog: Mapping[str, Mapping[str, Any]],
    bus: Any,
) -> Optional[Dict[str, Any]]:
    if not weapon_iid or wear_amount <= 0:
        return None
    try:
        result = items_wear.apply_wear(weapon_iid, wear_amount)
    except KeyError:
        return None
    if not isinstance(result, Mapping):
        return None
    payload = dict(result)
    if not payload.get("cracked"):
        return payload  # wear applied but no crack to announce
    inst = itemsreg.get_instance(weapon_iid) or {"item_id": weapon_iid}
    tpl = catalog.get(str(inst.get("item_id"))) or {}
    name = item_label(inst, tpl, show_charges=False)
    bus.push("COMBAT/INFO", f"Your {name} cracks!")
    payload.setdefault("iid", weapon_iid)
    payload.setdefault("item_id", str(inst.get("item_id")))
    payload["item_name"] = name
    return payload


def _sync_monster_armour_view(
    monster: MutableMapping[str, Any],
    armour: MutableMapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    derived = dict(monster.get("derived") or {})
    armour_payload = dict(armour.get("derived") or {})
    if result.get("cracked"):
        armour["item_id"] = itemsreg.BROKEN_ARMOUR_ID
        armour["enchant_level"] = 0
        armour["enchanted"] = "no"
        armour["condition"] = 0
        armour_payload["armour_class"] = 0
    else:
        condition = result.get("condition")
        if isinstance(condition, int):
            armour["condition"] = condition
    armour["derived"] = armour_payload
    dex_bonus = derived.get("dex_bonus", 0)
    armour_bonus = armour_payload.get("armour_class", 0)
    derived["armour_class"] = dex_bonus + armour_bonus
    monster["derived"] = derived


def _apply_armour_local(
    monster: MutableMapping[str, Any],
    armour: MutableMapping[str, Any],
    wear_amount: int,
) -> Optional[Dict[str, Any]]:
    if wear_amount <= 0:
        return None
    try:
        current = int(armour.get("condition", 0))
    except (TypeError, ValueError):
        current = 0
    enchanted_flag = str(armour.get("enchanted", "")).lower()
    enchant_level = armour.get("enchant_level", 0)
    if enchanted_flag == "yes" or (isinstance(enchant_level, int) and enchant_level > 0):
        return {"cracked": False, "condition": current}
    if current <= 0:
        _sync_monster_armour_view(monster, armour, {"cracked": False, "condition": 0})
        return {"cracked": False, "condition": 0}
    next_condition = max(0, current - wear_amount)
    payload: Dict[str, Any] = {"cracked": next_condition <= 0, "condition": next_condition}
    _sync_monster_armour_view(monster, armour, payload)
    return payload


def _apply_armour_wear(
    monster: MutableMapping[str, Any],
    wear_amount: int,
    catalog: Mapping[str, Mapping[str, Any]],
    bus: Any,
) -> Optional[Dict[str, Any]]:
    armour = _resolve_target_armour(monster)
    if armour is None or wear_amount <= 0:
        return None
    iid = armour.get("iid") or armour.get("instance_id")
    iid_str = str(iid) if iid else None
    result: Optional[Dict[str, Any]] = None
    if iid_str:
        try:
            result = items_wear.apply_wear(iid_str, wear_amount)
        except KeyError:
            result = None
    if result is None:
        result = _apply_armour_local(monster, armour, wear_amount)
    else:
        _sync_monster_armour_view(monster, armour, result)
    if not result:
        return None
    payload = dict(result)
    if payload.get("cracked"):
        inst: Mapping[str, Any] | None = None
        if iid_str:
            inst = itemsreg.get_instance(iid_str)
        if not inst:
            inst = {"item_id": armour.get("item_id"), "iid": iid_str}
        tpl = catalog.get(str(inst.get("item_id"))) or {}
        target_name = _monster_display_name(monster, str(monster.get("id") or "target"))
        suffix = "'" if target_name.endswith("s") else "'s"
        name = item_label(inst, tpl, show_charges=False)
        bus.push("COMBAT/INFO", f"{target_name}{suffix} {name} cracks!")
        payload.setdefault("iid", iid_str)
        payload.setdefault("item_id", str(inst.get("item_id")))
        payload["item_name"] = name
    return payload


def _clamp_melee_damage(monster: Mapping[str, Any], damage: int) -> int:
    if damage <= 0:
        return 0
    current, maximum = _sanitize_hp(monster)
    if maximum <= 0:
        return damage
    if current != maximum or current <= 1:
        return damage
    if damage >= current:
        return max(0, current - 1)
    return damage


def _resolve_monster_payload(summary: Mapping[str, Any] | None, fallback: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(summary, Mapping):
        monster = summary.get("monster")
        if isinstance(monster, Mapping):
            return monster
    return fallback


def _resolve_drop_entries(summary: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(summary, Mapping):
        return []
    minted = summary.get("drops_minted")
    if isinstance(minted, Sequence):
        result_minted: list[Mapping[str, Any]] = []
        for entry in minted:
            if isinstance(entry, Mapping):
                result_minted.append(entry)
        if result_minted:
            return result_minted
    drops = summary.get("drops")
    if not isinstance(drops, Sequence):
        return []
    result: list[Mapping[str, Any]] = []
    for entry in drops:
        if isinstance(entry, Mapping):
            result.append(entry)
    return result


def _monster_exp_bonus(monster_payload: Mapping[str, Any]) -> int:
    bonus = _coerce_int(monster_payload.get("exp_bonus"), 0)
    if bonus:
        return bonus
    monster_id = monster_payload.get("monster_id")
    if not monster_id:
        return 0
    try:
        catalog = load_monsters_catalog()
    except FileNotFoundError:
        return 0
    base = catalog.get(str(monster_id)) if catalog else None
    if isinstance(base, Mapping):
        return _coerce_int(base.get("exp_bonus"), 0)
    return 0


def _award_player_progress(
    *,
    monster_payload: Mapping[str, Any],
    state: Mapping[str, Any],
    item_catalog: Mapping[str, Mapping[str, Any]],
    summary: Mapping[str, Any] | None,
    bus: Any,
) -> Dict[str, int]:
    gains: Dict[str, int] = {"ions": 0, "riblets": 0, "xp": 0}
    ions_reward = _coerce_int(monster_payload.get("ions"), 0)
    if ions_reward:
        current_ions = pstate.get_ions_for_active(state)
        pstate.set_ions_for_active(state, current_ions + ions_reward)
        gains["ions"] = ions_reward

    riblets_reward = _coerce_int(monster_payload.get("riblets"), 0)
    if riblets_reward:
        current_riblets = pstate.get_riblets_for_active(state)
        pstate.set_riblets_for_active(state, current_riblets + riblets_reward)
        gains["riblets"] = riblets_reward

    level = max(1, _coerce_int(monster_payload.get("level"), 1))
    exp_bonus = _monster_exp_bonus(monster_payload)
    exp_reward = monster_exp_for(level, exp_bonus)
    if exp_reward:
        current_exp = pstate.get_exp_for_active(state)
        pstate.set_exp_for_active(state, current_exp + exp_reward)
        gains["xp"] = exp_reward

    pos = _coerce_pos(summary.get("pos") if isinstance(summary, Mapping) else None)
    if pos is None:
        pos = _coerce_pos(monster_payload.get("pos"))

    if pos is None:
        player_state = dict(state)
        active = player_state.get("active") if isinstance(player_state, Mapping) else None
        pos = _coerce_pos(active.get("pos")) if isinstance(active, Mapping) else None
    if pos is None:
        pos = _coerce_pos(state.get("pos")) if isinstance(state, Mapping) else None
    if pos is None:
        return gains

    drop_entries = _resolve_drop_entries(summary)
    bag_entries: list[Mapping[str, Any]] = []
    armour_entry: Mapping[str, Any] | None = None
    if isinstance(summary, MutableMapping):
        raw_bag = summary.get("bag_drops")
        if isinstance(raw_bag, Sequence):
            for entry in raw_bag:
                if isinstance(entry, Mapping):
                    bag_entries.append(entry)
        candidate_armour = summary.get("armour_drop")
        if isinstance(candidate_armour, Mapping):
            armour_entry = candidate_armour
    if not bag_entries and drop_entries:
        bag_entries = list(drop_entries)
    minted, vaporized = combat_loot.drop_monster_loot(
        pos=pos,
        bag_entries=bag_entries,
        armour_entry=armour_entry,
        bus=bus,
        catalog=item_catalog,
    )
    if isinstance(summary, MutableMapping):
        summary["drops_minted"] = minted
        summary["drops_vaporized"] = vaporized

    return gains


def _coerce_iid(value: Any) -> Optional[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, Mapping):
        for key in ("wielded", "iid", "instance_id", "weapon"):
            candidate = _coerce_iid(value.get(key))
            if candidate:
                return candidate
    return None


def _extract_wielded_iid(payload: Any, cls: Optional[str]) -> Optional[str]:
    if not isinstance(payload, Mapping):
        return None
    direct = _coerce_iid(payload.get("wielded"))
    if direct:
        return direct
    if cls:
        wield_map = payload.get("wielded_by_class")
        if isinstance(wield_map, Mapping):
            entry = wield_map.get(cls)
            candidate = _coerce_iid(entry)
            if candidate:
                return candidate
    return None


def strike_cmd(arg: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a combat strike using the active player and return a summary payload."""

    bus = ctx.get("feedback_bus")
    if bus is None:
        raise ValueError("strike command requires feedback_bus in context")

    monsters = _load_monsters(ctx)
    if monsters is None:
        bus.push("SYSTEM/WARN", "No monsters are available to strike.")
        return {"ok": False, "reason": "no_monsters"}

    state, active = pstate.get_active_pair()
    target_id = pstate.get_ready_target_for_active(state)
    if not target_id:
        bus.push("SYSTEM/WARN", "You're not ready to combat anyone!")
        return {"ok": False, "reason": "no_target"}

    target = None
    getter = getattr(monsters, "get", None)
    if callable(getter):
        target = getter(target_id)
    if target is None:
        bus.push("SYSTEM/WARN", "Your target is nowhere to be found.")
        pstate.clear_ready_target_for_active(reason="target-missing")
        return {"ok": False, "reason": "target_missing"}

    if not isinstance(target, MutableMapping):
        bus.push("SYSTEM/WARN", "You cannot strike that target.")
        return {"ok": False, "reason": "invalid_target"}

    if not _is_alive(target):
        bus.push("SYSTEM/WARN", "Your target is already dead.")
        pstate.clear_ready_target_for_active(reason="target-dead")
        return {"ok": False, "reason": "target_dead"}

    catalog = {}  # type: Dict[str, Mapping[str, Any]]
    try:
        catalog = items_catalog.load_catalog() or {}
    except FileNotFoundError:
        catalog = {}

    cls_name = pstate.get_active_class(state)
    weapon_iid = pstate.get_wielded_weapon_id(state)
    if not weapon_iid:
        weapon_iid = pstate.get_wielded_weapon_id(active)
    if not weapon_iid:
        weapon_iid = _extract_wielded_iid(state, cls_name)
    if not weapon_iid:
        weapon_iid = _extract_wielded_iid(active, cls_name)
    if not weapon_iid:
        weapon_iid = pstate.get_wielded_weapon_id(pstate.load_state())
    if not weapon_iid:
        weapon_iid = _extract_wielded_iid(pstate.load_state(), cls_name)
    damage_item = weapon_iid if weapon_iid else {}
    attack = damage_engine.resolve_attack(damage_item, active, target)
    final_damage = max(0, int(attack.damage))
    if attack.source == "bolt":
        final_damage = max(MIN_BOLT_DAMAGE, final_damage)

    final_damage = _clamp_melee_damage(target, final_damage)

    if final_damage > 0:
        try:
            damage_engine.wake_target_if_asleep(ctx, target)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Failed to wake monster after strike", extra={"target": target_id})

    wear_event = items_wear.build_wear_event(actor="player", source=str(attack.source), damage=final_damage)
    wear_amount = items_wear.wear_from_event(wear_event)

    weapon_wear: Mapping[str, Any] | None = None
    armour_wear: Mapping[str, Any] | None = None
    if final_damage > 0:
        weapon_wear = _apply_weapon_wear(weapon_iid, wear_amount, catalog, bus)
        if isinstance(target, MutableMapping):
            armour_wear = _apply_armour_wear(target, wear_amount, catalog, bus)

    current_hp, max_hp = _sanitize_hp(target)
    new_hp = max(0, current_hp - final_damage)
    hp_block = target.setdefault("hp", {})
    if isinstance(hp_block, MutableMapping):
        hp_block["current"] = new_hp
        if "max" not in hp_block:
            hp_block["max"] = max_hp

    result: Dict[str, Any] = {
        "ok": True,
        "damage": final_damage,
        "target_id": target_id,
        "remaining_hp": new_hp,
    }

    label = _monster_display_name(target, target_id)
    bus.push("COMBAT/HIT", f"You strike {label} for {final_damage} damage.")

    if weapon_wear and weapon_wear.get("cracked"):
        turnlog.emit(
            ctx,
            "ITEM/CRACK",
            owner="player",
            item_id=weapon_wear.get("item_id"),
            item_name=weapon_wear.get("item_name"),
            iid=weapon_iid,
            source="weapon",
        )
    if armour_wear and armour_wear.get("cracked"):
        turnlog.emit(
            ctx,
            "ITEM/CRACK",
            owner="monster",
            target=target_id,
            item_id=armour_wear.get("item_id"),
            item_name=armour_wear.get("item_name"),
            iid=armour_wear.get("iid"),
            source="armour",
        )

    strike_meta = {
        "actor": "player",
        "target": target_id,
        "target_name": label,
        "damage": final_damage,
        "remaining_hp": new_hp,
        "weapon_iid": weapon_iid,
    }

    killed = final_damage > 0 and new_hp <= 0
    strike_meta["killed"] = killed
    turnlog.emit(ctx, "COMBAT/STRIKE", **strike_meta)
    if killed:
        killer_id = str(active.get("id") or state.get("active_id") or "player")
        killer_label = pstate.get_active_class(state)
        killer_meta = {"killer_id": killer_id, "killer_class": killer_label, "victim_id": target_id}
        finisher = getattr(monsters, "kill_monster", None)
        summary: Mapping[str, Any] | None = None
        if callable(finisher):
            try:
                summary = finisher(target_id)
            except Exception:
                summary = None
        bus.push("COMBAT/KILL", f"You have slain {label}!", **killer_meta)
        try:
            monster_payload = _resolve_monster_payload(summary, target)
            rewards = _award_player_progress(
                monster_payload=monster_payload,
                state=state,
                item_catalog=catalog,
                summary=summary,
                bus=bus,
            )
            xp_gain = rewards.get("xp", 0)
            if xp_gain:
                bus.push("COMBAT/INFO", f"Your experience points are increased by {xp_gain}!")
            riblets_gain = rewards.get("riblets", 0)
            ions_gain = rewards.get("ions", 0)
            if riblets_gain or ions_gain:
                if riblets_gain and ions_gain:
                    bus.push(
                        "COMBAT/INFO",
                        f"You collect {riblets_gain} Riblets and {ions_gain} ions from the slain body.",
                    )
                elif riblets_gain:
                    bus.push(
                        "COMBAT/INFO",
                        f"You collect {riblets_gain} Riblets from the slain body.",
                    )
                else:
                    bus.push(
                        "COMBAT/INFO",
                        f"You collect {ions_gain} ions from the slain body.",
                    )
        except Exception:
            pass
        drops = _resolve_drop_entries(summary)
        if drops:
            drop_catalog = catalog
            for entry in drops:
                item_key = (
                    entry.get("item_id")
                    or entry.get("catalog_id")
                    or entry.get("id")
                    or ""
                )
                template = drop_catalog.get(str(item_key)) if drop_catalog else {}
                name = item_label(entry, template or {}, show_charges=False)
                article = with_article(name)
                bus.push("COMBAT/INFO", f"{article} is falling from {label}'s body!")
        turnlog.emit(
            ctx,
            "COMBAT/KILL",
            actor=killer_id,
            victim=target_id,
            drops=len(drops),
            source="player",
        )
        pstate.clear_ready_target_for_active(reason="monster-dead")
        bus.push("COMBAT/INFO", f"{label} is crumbling to dust!")
        try:
            from mutants.services import monster_actions as monster_actions_mod

            monster_actions_mod.notify_monster_death(summary or target, ctx=ctx)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Failed to notify monster spawner after kill")
        result["killed"] = True
    else:
        marker = getattr(monsters, "mark_dirty", None)
        if callable(marker):
            try:
                marker()
            except Exception:
                pass
    return result


def register(dispatch, ctx) -> None:
    dispatch.register("strike", lambda arg: strike_cmd(arg, ctx))
    dispatch.alias("str", "strike")
    dispatch.alias("hit", "strike")
    dispatch.alias("att", "strike")
