"""Monster action helpers implementing basic deterministic behaviours."""

from __future__ import annotations

import logging
import random
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional

from mutants.commands import convert as convert_cmd
from mutants.commands import strike
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_loot
from mutants.services import damage_engine, items_wear, monsters_state, player_state as pstate
from mutants.ui import item_display

LOG = logging.getLogger(__name__)


MIN_INNATE_DAMAGE = strike.MIN_INNATE_DAMAGE


ActionFn = Callable[[MutableMapping[str, Any], MutableMapping[str, Any], random.Random], bool]


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("name") or monster.get("monster_id")
    if isinstance(name, str) and name:
        return name
    ident = monster.get("id") or monster.get("instance_id")
    if isinstance(ident, str) and ident:
        return ident
    return "The monster"


def _feedback_bus(ctx: MutableMapping[str, Any]) -> Any:
    bus = ctx.get("feedback_bus")
    return bus


def _monsters_state(ctx: MutableMapping[str, Any]) -> Optional[Any]:
    monsters = ctx.get("monsters")
    return monsters


def _mark_monsters_dirty(ctx: MutableMapping[str, Any]) -> None:
    monsters = _monsters_state(ctx)
    marker = getattr(monsters, "mark_dirty", None)
    if callable(marker):
        try:
            marker()
        except Exception:  # pragma: no cover - defensive
            LOG.exception("Failed to mark monsters state dirty")


def _sanitize_hp_block(payload: Any) -> tuple[int, int]:
    if isinstance(payload, Mapping):
        try:
            current = int(payload.get("current", 0))
        except (TypeError, ValueError):
            current = 0
        try:
            maximum = int(payload.get("max", current))
        except (TypeError, ValueError):
            maximum = current
        return max(0, current), max(0, maximum)
    return 0, 0


def _ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    payload = monster.get("_ai_state")
    if not isinstance(payload, MutableMapping):
        payload = {}
        monster["_ai_state"] = payload
    pickups = payload.get("picked_up")
    if not isinstance(pickups, list):
        payload["picked_up"] = []
    return payload


def _picked_up_iids(monster: MutableMapping[str, Any]) -> list[str]:
    state = _ai_state(monster)
    pickups = state.get("picked_up")
    if isinstance(pickups, list):
        return [str(iid) for iid in pickups if isinstance(iid, str)]
    return []


def _add_picked_up(monster: MutableMapping[str, Any], iid: str) -> None:
    state = _ai_state(monster)
    pickups = state.get("picked_up")
    if not isinstance(pickups, list):
        pickups = []
        state["picked_up"] = pickups
    if iid not in pickups:
        pickups.append(iid)


def _remove_picked_up(monster: MutableMapping[str, Any], iid: str) -> None:
    state = _ai_state(monster)
    pickups = state.get("picked_up")
    if isinstance(pickups, list):
        try:
            pickups.remove(iid)
        except ValueError:
            pass


def _load_catalog() -> Mapping[str, Mapping[str, Any]]:
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = None
    if isinstance(catalog, Mapping):
        return catalog
    return {}


def _resolve_item_id(inst: Mapping[str, Any]) -> str:
    for key in ("item_id", "catalog_id", "id"):
        value = inst.get(key)
        if isinstance(value, str) and value:
            return value
        if value:
            return str(value)
    iid = inst.get("iid") or inst.get("instance_id")
    return str(iid) if iid else ""


def _convert_value(catalog: Mapping[str, Any], iid: str, item_id: str) -> int:
    try:
        return convert_cmd._convert_value(item_id, catalog, iid)
    except Exception:
        return 0


def _score_pickup_candidate(
    inst: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> int:
    item_id = _resolve_item_id(inst)
    tpl = catalog.get(item_id) if item_id else None
    base_power = 0
    if isinstance(tpl, Mapping):
        try:
            base_power = int(tpl.get("base_power", 0))
        except (TypeError, ValueError):
            base_power = 0
    enchant = 0
    try:
        enchant = int(inst.get("enchant_level", 0))
    except (TypeError, ValueError):
        enchant = 0
    base_damage = max(0, base_power) + (4 * max(0, enchant))
    convert_val = _convert_value(catalog, str(inst.get("iid")), item_id)
    return (base_damage * 1000) + max(0, convert_val)


def _bag_list(monster: MutableMapping[str, Any]) -> list[MutableMapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, list):
        cleaned: list[MutableMapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, MutableMapping):
                cleaned.append(entry)
        if cleaned is not bag:
            monster["bag"] = cleaned
        return cleaned
    monster["bag"] = []
    return monster["bag"]  # type: ignore[return-value]


def _build_bag_entry(
    monster: MutableMapping[str, Any],
    inst: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> MutableMapping[str, Any]:
    iid = inst.get("iid") or inst.get("instance_id")
    entry: MutableMapping[str, Any] = {"iid": str(iid) if iid else ""}
    entry["item_id"] = _resolve_item_id(inst)
    enchant = 0
    try:
        enchant = int(inst.get("enchant_level", 0))
    except (TypeError, ValueError):
        enchant = 0
    entry["enchant_level"] = max(0, enchant)
    condition = inst.get("condition")
    try:
        entry["condition"] = max(0, int(condition))
    except (TypeError, ValueError):
        if condition is not None:
            entry["condition"] = 0
    tpl = catalog.get(entry["item_id"])
    derived: dict[str, int] = {}
    if isinstance(tpl, Mapping) and tpl.get("armour"):
        try:
            armour_base = int(tpl.get("armour_class", 0))
        except (TypeError, ValueError):
            armour_base = 0
        derived["armour_class"] = max(0, armour_base) + entry["enchant_level"]
    if isinstance(tpl, Mapping) and tpl.get("base_power") is not None:
        try:
            base_power = int(tpl.get("base_power", 0))
        except (TypeError, ValueError):
            base_power = 0
        derived["base_damage"] = max(0, base_power) + (4 * entry["enchant_level"])
    if derived:
        entry["derived"] = derived
    return entry


def _refresh_monster(monster: MutableMapping[str, Any]) -> None:
    try:
        monsters_state._refresh_monster_derived(monster)
    except Exception:  # pragma: no cover - defensive
        LOG.exception("Failed to refresh monster derived stats")


def _apply_weapon_wear(
    monster: MutableMapping[str, Any],
    weapon_iid: Optional[str],
    wear_amount: int,
    catalog: Mapping[str, Mapping[str, Any]],
    bus: Any,
) -> None:
    if not weapon_iid or wear_amount <= 0:
        return
    try:
        result = items_wear.apply_wear(weapon_iid, wear_amount)
    except KeyError:
        return
    if not isinstance(result, Mapping):
        return
    bag = _bag_list(monster)
    for entry in bag:
        if entry.get("iid") == weapon_iid:
            inst = itemsreg.get_instance(weapon_iid)
            if inst:
                entry["item_id"] = _resolve_item_id(inst)
                if inst.get("condition") is not None:
                    try:
                        entry["condition"] = max(0, int(inst.get("condition", 0)))
                    except (TypeError, ValueError):
                        entry["condition"] = 0
                else:
                    entry.pop("condition", None)
                entry["enchant_level"] = max(0, int(inst.get("enchant_level", 0) or 0))
            break
    if result.get("cracked"):
        inst = itemsreg.get_instance(weapon_iid) or {"item_id": weapon_iid}
        tpl = catalog.get(str(inst.get("item_id"))) or {}
        name = item_display.item_label(inst, tpl, show_charges=False)
        if bus is not None and hasattr(bus, "push"):
            bus.push("COMBAT/INFO", f"{_monster_display_name(monster)}'s {name} cracks!")
    _refresh_monster(monster)


def _collect_player_items(state: Mapping[str, Any], active: Mapping[str, Any], cls: str) -> list[str]:
    collected: list[str] = []

    def _append(items: Iterable[Any]) -> None:
        for item in items:
            if not item:
                continue
            token = str(item)
            if token and token not in collected:
                collected.append(token)

    if isinstance(state.get("inventory"), list):
        _append(state.get("inventory"))
    if isinstance(active.get("inventory"), list):
        _append(active.get("inventory"))

    bags = state.get("bags") if isinstance(state.get("bags"), Mapping) else {}
    if isinstance(bags, Mapping):
        bag_items = bags.get(cls)
        if isinstance(bag_items, list):
            _append(bag_items)

    bags_by_class = state.get("bags_by_class") if isinstance(state.get("bags_by_class"), Mapping) else {}
    if isinstance(bags_by_class, Mapping):
        bag_items = bags_by_class.get(cls)
        if isinstance(bag_items, list):
            _append(bag_items)

    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, Mapping):
                continue
            if isinstance(player.get("inventory"), list):
                _append(player.get("inventory"))
            pbags = player.get("bags") if isinstance(player.get("bags"), Mapping) else {}
            if isinstance(pbags, Mapping):
                bag_items = pbags.get(cls)
                if isinstance(bag_items, list):
                    _append(bag_items)
    return collected


def _clear_player_inventory(state: MutableMapping[str, Any], active: MutableMapping[str, Any], cls: str) -> None:
    scopes: list[MutableMapping[str, Any]] = []
    scopes.append(state)
    if isinstance(active, MutableMapping):
        scopes.append(active)
    players = state.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, MutableMapping):
                scopes.append(player)

    for scope in scopes:
        bags = scope.setdefault("bags", {})
        if isinstance(bags, MutableMapping):
            bags[cls] = []
        if isinstance(scope.get("bags_by_class"), MutableMapping):
            scope["bags_by_class"][cls] = []  # type: ignore[index]
        scope["inventory"] = []
        equip_map = scope.get("equipment_by_class")
        if isinstance(equip_map, MutableMapping):
            equip_map[cls] = {"armour": None}
        wield_map = scope.get("wielded_by_class")
        if isinstance(wield_map, MutableMapping):
            wield_map[cls] = None
        scope["wielded"] = None
        armour = scope.get("armour")
        if isinstance(armour, MutableMapping):
            armour["wearing"] = None
        elif armour is not None:
            scope["armour"] = {"wearing": None}


def _handle_player_death(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    state: MutableMapping[str, Any],
    active: MutableMapping[str, Any],
    bus: Any,
) -> None:
    label = _monster_display_name(monster)
    killer_id = str(monster.get("id") or monster.get("instance_id") or "monster")
    victim_id = str(active.get("id") or state.get("active_id") or "player")
    victim_class = pstate.get_active_class(state)

    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{label} slays you!")
        bus.push(
            "COMBAT/KILL",
            f"{label} slays you!",
            killer_id=killer_id,
            victim_id=victim_id,
            victim_class=victim_class,
        )

    ions = pstate.get_ions_for_active(state)
    if ions:
        monster["ions"] = _coerce_int(monster.get("ions"), 0) + ions
        pstate.set_ions_for_active(state, 0)

    riblets = pstate.get_riblets_for_active(state)
    if riblets:
        monster["riblets"] = _coerce_int(monster.get("riblets"), 0) + riblets
        pstate.set_riblets_for_active(state, 0)

    pos = combat_loot.coerce_pos(active.get("pos")) or combat_loot.coerce_pos(state.get("pos"))
    if pos is None:
        pos = (2000, 0, 0)

    catalog = _load_catalog()
    inventory_iids = _collect_player_items(state, active, victim_class)
    dropped: list[str] = []
    if inventory_iids:
        dropped.extend(combat_loot.drop_existing_iids(inventory_iids, pos))
    armour_iid = pstate.get_equipped_armour_id(state)
    if armour_iid and armour_iid not in dropped:
        dropped.extend(combat_loot.drop_existing_iids([armour_iid], pos))
    if dropped:
        combat_loot.enforce_capacity(pos, dropped, bus=bus, catalog=catalog)

    _clear_player_inventory(state, active, victim_class)
    try:
        pstate.clear_ready_target_for_active(reason="player-dead")
    except Exception:
        pass
    pstate.save_state(state)
    _mark_monsters_dirty(ctx)


def _apply_player_damage(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> bool:
    bus = _feedback_bus(ctx)
    state_hint = ctx.get("player_state") if isinstance(ctx.get("player_state"), Mapping) else None
    try:
        state, active = pstate.get_active_pair(state_hint)
    except Exception:
        state, active = pstate.get_active_pair()
    if not isinstance(active, Mapping) or not active:
        return False
    hp_block = active.get("hp") if isinstance(active.get("hp"), Mapping) else pstate.get_hp_for_active(state)
    current, maximum = _sanitize_hp_block(hp_block)
    if maximum <= 0:
        maximum = max(current, 1)
    weapon_iid = monster.get("wielded")
    damage_item: Any
    if weapon_iid:
        damage_item = weapon_iid
    else:
        damage_item = {}
    raw_damage = damage_engine.compute_base_damage(damage_item, monster, active)
    try:
        final_damage = max(0, int(raw_damage))
    except (TypeError, ValueError):
        final_damage = 0
    if not weapon_iid:
        final_damage = max(MIN_INNATE_DAMAGE, final_damage)
    final_damage = strike._clamp_melee_damage(active, final_damage)
    if final_damage > 0:
        wear_amount = items_wear.wear_from_event({"kind": "monster-attack", "damage": final_damage})
        catalog = _load_catalog()
        bus_obj = bus if hasattr(bus, "push") else None
        _apply_weapon_wear(monster, str(weapon_iid) if weapon_iid else None, wear_amount, catalog, bus_obj)
        if weapon_iid:
            _mark_monsters_dirty(ctx)
    new_hp = max(0, current - final_damage)
    try:
        pstate.set_hp_for_active(state, {"current": new_hp, "max": maximum})
    except Exception:  # pragma: no cover - defensive
        LOG.exception("Failed to persist player HP after monster attack")
    label = _monster_display_name(monster)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{label} strikes you for {final_damage} damage.")
    if final_damage > 0 and new_hp <= 0:
        if isinstance(state, MutableMapping) and isinstance(active, MutableMapping):
            _handle_player_death(monster, ctx, state, active, bus)
    return True


def _pickup_from_ground(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> bool:
    pos = monster.get("pos")
    if not isinstance(pos, Iterable):
        return False
    coords = list(pos)
    if len(coords) != 3:
        return False
    try:
        year, x, y = int(coords[0]), int(coords[1]), int(coords[2])
    except (TypeError, ValueError):
        return False
    ground = itemsreg.list_instances_at(year, x, y)
    if not ground:
        return False
    catalog = _load_catalog()
    best_inst: Optional[Mapping[str, Any]] = None
    best_score = -1
    for inst in ground:
        if not isinstance(inst, Mapping):
            continue
        score = _score_pickup_candidate(inst, catalog)
        if score > best_score:
            best_score = score
            best_inst = inst
    if not best_inst or best_score <= 0:
        return False
    iid = best_inst.get("iid") or best_inst.get("instance_id")
    if not iid:
        return False
    iid_str = str(iid)
    if not itemsreg.clear_position_at(iid_str, year, x, y):
        return False
    entry = _build_bag_entry(monster, best_inst, catalog)
    bag = _bag_list(monster)
    bag.append(entry)
    _add_picked_up(monster, iid_str)
    _refresh_monster(monster)
    _mark_monsters_dirty(ctx)
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        tpl = catalog.get(entry.get("item_id", "")) or {}
        inst = {"item_id": entry.get("item_id"), "iid": iid_str}
        name = item_display.item_label(inst, tpl, show_charges=False)
        bus.push("COMBAT/INFO", f"{_monster_display_name(monster)} picks up {name}.")
    return True


def _convert_item(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> bool:
    bag = _bag_list(monster)
    if not bag:
        return False
    tracked = set(_picked_up_iids(monster))
    if not tracked:
        return False
    catalog = _load_catalog()
    best_entry: Optional[MutableMapping[str, Any]] = None
    best_value = 0
    for entry in bag:
        iid = entry.get("iid")
        if not isinstance(iid, str) or iid not in tracked:
            continue
        item_id = entry.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            continue
        value = _convert_value(catalog, iid, item_id)
        if value > best_value:
            best_value = value
            best_entry = entry
    if not best_entry or best_value <= 0:
        return False
    iid = str(best_entry.get("iid"))
    if best_entry in bag:
        bag.remove(best_entry)
    _remove_picked_up(monster, iid)
    if monster.get("wielded") == iid:
        monster["wielded"] = None
    itemsreg.delete_instance(iid)
    monster["ions"] = max(0, int(monster.get("ions", 0))) + best_value
    _refresh_monster(monster)
    _mark_monsters_dirty(ctx)
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        label = _monster_display_name(monster)
        bus.push("COMBAT/INFO", f"A blinding white flash erupts around {label}!")
        bus.push(
            "COMBAT/INFO",
            f"{label} converts loot worth {best_value} ions.",
        )
    return True


def _remove_broken_armour(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> bool:
    armour = monster.get("armour_slot")
    if not isinstance(armour, MutableMapping):
        return False
    item_id = armour.get("item_id")
    if str(item_id) != itemsreg.BROKEN_ARMOUR_ID:
        return False
    monster["armour_slot"] = None
    _refresh_monster(monster)
    _mark_monsters_dirty(ctx)
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{_monster_display_name(monster)} discards broken armour.")
    return True


def _heal_stub(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> bool:
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{_monster_display_name(monster)}'s body is glowing.")
    return True


_ACTION_TABLE: dict[str, ActionFn] = {
    "attack": _apply_player_damage,
    "pickup": _pickup_from_ground,
    "convert": _convert_item,
    "remove_armour": _remove_broken_armour,
    "heal": _heal_stub,
}


def _action_weights(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
) -> list[tuple[str, float]]:
    current, maximum = _sanitize_hp_block(monster.get("hp"))
    hp_ratio = 1.0
    if maximum > 0:
        hp_ratio = current / maximum if maximum else 1.0
    bag = _bag_list(monster)
    tracked = _picked_up_iids(monster)
    weights: list[tuple[str, float]] = [("attack", 6.0)]
    pickup_weight = 1.5 if hp_ratio < 0.5 else 1.0
    convert_weight = 1.0 if tracked else 0.0
    if hp_ratio < 0.5 and convert_weight:
        convert_weight *= 1.5
    armour = monster.get("armour_slot")
    remove_weight = 1.0 if isinstance(armour, Mapping) and str(armour.get("item_id")) == itemsreg.BROKEN_ARMOUR_ID else 0.0
    if itemsreg.BROKEN_ARMOUR_ID in {str(entry.get("item_id")) for entry in bag}:
        pickup_weight *= 1.1
    heal_enabled = bool(ctx.get("monster_ai_allow_heal"))
    heal_weight = 0.0
    if heal_enabled and hp_ratio < 0.9:
        ions = 0
        try:
            ions = int(monster.get("ions", 0))
        except (TypeError, ValueError):
            ions = 0
        if ions > 0:
            heal_weight = 0.5
    weights.append(("pickup", pickup_weight if pickup_weight > 0 and ctx.get("allow_pickup", True) else 0.0))
    weights.append(("convert", convert_weight))
    weights.append(("remove_armour", remove_weight))
    weights.append(("heal", heal_weight))
    return weights


def _select_action(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Optional[str]:
    weighted = [(name, weight) for name, weight in _action_weights(monster, ctx) if weight > 0]
    if not weighted:
        return None
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        return None
    roll = rng.random() * total
    cumulative = 0.0
    for name, weight in weighted:
        cumulative += weight
        if roll < cumulative:
            return name
    return weighted[-1][0]


def execute_random_action(monster: Any, ctx: Any, *, rng: Any | None = None) -> None:
    if not isinstance(monster, MutableMapping):
        return None
    if not isinstance(ctx, MutableMapping):
        return None
    random_obj = rng if isinstance(rng, random.Random) else random.Random()
    action_name = _select_action(monster, ctx, random_obj)
    if not action_name:
        return None
    action = _ACTION_TABLE.get(action_name)
    if not action:
        return None
    try:
        action(monster, ctx, random_obj)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Monster action %s failed", action_name)
    return None

