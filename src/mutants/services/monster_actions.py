"""Monster action helpers implementing basic deterministic behaviours."""

from __future__ import annotations

import logging
import random
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Optional

from mutants.commands import convert as convert_cmd
from mutants.commands import strike
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_loot
from mutants.services import damage_engine, items_wear, monsters_state, player_state as pstate
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai.attack_selection import select_attack
from mutants.services.monster_ai.cascade import evaluate_cascade
from mutants.services.monster_ai import inventory as inventory_mod
from mutants.services.monster_ai import heal as heal_mod
from mutants.services.monster_ai import casting as casting_mod
from mutants.debug import turnlog
from mutants.ui import item_display

LOG = logging.getLogger(__name__)

ORIGIN_NATIVE = "native"
ORIGIN_WORLD = "world"


MIN_INNATE_DAMAGE = strike.MIN_INNATE_DAMAGE
MIN_BOLT_DAMAGE = strike.MIN_BOLT_DAMAGE


ActionFn = Callable[[MutableMapping[str, Any], MutableMapping[str, Any], random.Random], Any]


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


def _monster_id(monster: Mapping[str, Any]) -> str:
    ident = monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
    if isinstance(ident, str) and ident:
        return ident
    return "?"


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


def _sanitize_player_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        return token or None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _normalize_player_pos(
    state: Mapping[str, Any], active: Mapping[str, Any]
) -> Optional[tuple[int, int, int]]:
    pos = combat_loot.coerce_pos(active.get("pos"))
    if pos is None:
        pos = combat_loot.coerce_pos(state.get("pos"))
    return pos


def _ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    payload = monster.get("_ai_state")
    if not isinstance(payload, MutableMapping):
        payload = {}
        monster["_ai_state"] = payload
    pickups = payload.get("picked_up")
    if not isinstance(pickups, list):
        payload["picked_up"] = []
    return payload


def _ledger_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, int]:
    state = _ai_state(monster)
    ledger_raw = state.get("ledger")
    if isinstance(ledger_raw, MutableMapping):
        ledger = ledger_raw
    elif isinstance(ledger_raw, Mapping):
        ledger = dict(ledger_raw)
        state["ledger"] = ledger
    else:
        ledger = {}
        state["ledger"] = ledger

    ions = _coerce_int(ledger.get("ions"), 0)
    riblets = _coerce_int(ledger.get("riblets"), 0)

    if "ions" in monster:
        ions = _coerce_int(monster.get("ions"), 0)
    else:
        monster["ions"] = ions

    if "riblets" in monster:
        riblets = _coerce_int(monster.get("riblets"), 0)
    else:
        monster["riblets"] = riblets

    ledger["ions"] = ions
    ledger["riblets"] = riblets
    monster["ions"] = ions
    monster["riblets"] = riblets
    return ledger


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


_BROKEN_ITEM_IDS = {itemsreg.BROKEN_WEAPON_ID, itemsreg.BROKEN_ARMOUR_ID}


def _convert_value(
    catalog: Mapping[str, Any], iid: Optional[str], item_id: str
) -> int:
    try:
        return convert_cmd._convert_value(item_id, catalog, iid)
    except Exception:
        return 0


def _is_broken_placeholder(item_id: str) -> bool:
    return item_id in _BROKEN_ITEM_IDS


def _derived_base_damage(inst: Mapping[str, Any]) -> Optional[int]:
    derived = inst.get("derived")
    if not isinstance(derived, Mapping):
        return None
    base_damage = derived.get("base_damage")
    try:
        value = int(base_damage)
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _catalogue_base_damage(
    tpl: Optional[Mapping[str, Any]], enchant: int
) -> int:
    if not isinstance(tpl, Mapping):
        return 0
    for key in ("base_power_melee", "base_power"):
        if tpl.get(key) is None:
            continue
        try:
            base_power = int(tpl.get(key, 0))
        except (TypeError, ValueError):
            base_power = 0
        return max(0, base_power) + (4 * max(0, enchant))
    return 0


def _score_pickup_candidate(
    inst: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> int:
    item_id = _resolve_item_id(inst)
    if not item_id or _is_broken_placeholder(item_id):
        return 0
    tpl = catalog.get(item_id)
    enchant = 0
    try:
        enchant = int(inst.get("enchant_level", 0))
    except (TypeError, ValueError):
        enchant = 0
    base_damage = _derived_base_damage(inst)
    if base_damage is None:
        base_damage = _catalogue_base_damage(tpl, enchant)
    iid = inst.get("iid") or inst.get("instance_id")
    iid_token = None
    if iid is not None:
        token = str(iid)
        iid_token = token if token else None
    convert_val = _convert_value(catalog, iid_token, item_id)
    base_damage = max(0, base_damage)
    convert_val = max(0, convert_val)
    if base_damage <= 0 and convert_val <= 0:
        return 0
    return (base_damage * 1000) + convert_val


def _bag_list(monster: MutableMapping[str, Any]) -> list[MutableMapping[str, Any]]:
    bag = monster.get("bag")
    if isinstance(bag, list):
        cleaned: list[MutableMapping[str, Any]] = []
        for entry in bag:
            if isinstance(entry, MutableMapping):
                origin = entry.get("origin")
                if isinstance(origin, str) and origin.strip():
                    entry["origin"] = origin.strip().lower()
                else:
                    entry["origin"] = ORIGIN_NATIVE
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
    if isinstance(tpl, Mapping):
        for key in ("base_power_melee", "base_power"):
            if tpl.get(key) is None:
                continue
            try:
                base_power = int(tpl.get(key, 0))
            except (TypeError, ValueError):
                base_power = 0
            derived["base_damage"] = max(0, base_power) + (4 * entry["enchant_level"])
            break
    if derived:
        entry["derived"] = derived
    origin_raw = inst.get("origin")
    if isinstance(origin_raw, str) and origin_raw.strip():
        origin_token = origin_raw.strip().lower()
    else:
        origin_token = ORIGIN_WORLD
    entry["origin"] = origin_token
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
    ctx: MutableMapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not weapon_iid or wear_amount <= 0:
        return None
    try:
        result = items_wear.apply_wear(weapon_iid, wear_amount)
    except KeyError:
        return None
    if not isinstance(result, Mapping):
        return None
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
    payload = dict(result)
    if payload.get("cracked"):
        inst = itemsreg.get_instance(weapon_iid) or {"item_id": weapon_iid}
        tpl = catalog.get(str(inst.get("item_id"))) or {}
        name = item_display.item_label(inst, tpl, show_charges=False)
        if bus is not None and hasattr(bus, "push"):
            bus.push("COMBAT/INFO", f"{_monster_display_name(monster)}'s {name} cracks!")
        turnlog.emit(
            ctx,
            "ITEM/CRACK",
            owner="monster",
            owner_id=_monster_id(monster),
            item_id=str(inst.get("item_id")),
            item_name=name,
            iid=weapon_iid,
            source="weapon",
        )
        inventory_mod.schedule_weapon_drop(monster, weapon_iid)
    _refresh_monster(monster)
    return payload


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
    ledger = _ledger_state(monster)

    if ions:
        ledger["ions"] = _coerce_int(ledger.get("ions"), 0) + ions
        monster["ions"] = ledger["ions"]
        pstate.set_ions_for_active(state, 0)

    riblets = pstate.get_riblets_for_active(state)
    if riblets:
        ledger["riblets"] = _coerce_int(ledger.get("riblets"), 0) + riblets
        monster["riblets"] = ledger["riblets"]
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

    turnlog.emit(
        ctx,
        "COMBAT/KILL",
        actor=killer_id,
        victim=victim_id,
        victim_class=victim_class,
        drops=len(dropped),
        source="monster",
    )

    _clear_player_inventory(state, active, victim_class)
    pstate.clear_ready_target_for_active(reason="player-dead")
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
    except (TypeError, ValueError, KeyError, AttributeError):
        LOG.debug("Falling back to canonical active pair lookup", exc_info=True)
        state, active = pstate.get_active_pair()
    if not isinstance(active, Mapping) or not active:
        return False
    hp_block = active.get("hp") if isinstance(active.get("hp"), Mapping) else pstate.get_hp_for_active(state)
    current, maximum = _sanitize_hp_block(hp_block)
    if maximum <= 0:
        maximum = max(current, 1)
    plan = select_attack(monster, ctx)
    weapon_iid = plan.item_iid
    damage_item: Any
    if weapon_iid:
        damage_item = str(weapon_iid)
    else:
        damage_item = {}
    attack = damage_engine.resolve_attack(damage_item, monster, active, source=plan.source)
    try:
        final_damage = max(0, int(attack.damage))
    except (TypeError, ValueError):
        final_damage = 0
    if attack.source == "innate":
        final_damage = max(MIN_INNATE_DAMAGE, final_damage)
    if attack.source == "bolt":
        final_damage = max(MIN_BOLT_DAMAGE, final_damage)
    final_damage = strike._clamp_melee_damage(active, final_damage)
    if final_damage > 0:
        wear_event = items_wear.build_wear_event(actor="monster", source=str(attack.source), damage=final_damage)
        wear_amount = items_wear.wear_from_event(wear_event)
        catalog = _load_catalog()
        bus_obj = bus if hasattr(bus, "push") else None
        resolved_iid = str(weapon_iid) if weapon_iid else None
        _apply_weapon_wear(
            monster,
            resolved_iid,
            wear_amount,
            catalog,
            bus_obj,
            ctx if isinstance(ctx, MutableMapping) else None,
        )
        if resolved_iid:
            _mark_monsters_dirty(ctx)
    new_hp = max(0, current - final_damage)
    try:
        pstate.set_hp_for_active(state, {"current": new_hp, "max": maximum})
    except Exception:  # pragma: no cover - defensive
        LOG.exception("Failed to persist player HP after monster attack")
    label = _monster_display_name(monster)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{label} strikes you for {final_damage} damage.")
    killed_flag = final_damage > 0 and new_hp <= 0
    if final_damage > 0:
        turnlog.emit(
            ctx,
            "AI/ACT/ATTACK",
            monster=_monster_id(monster),
            damage=final_damage,
            hp_after=new_hp,
            killed=killed_flag,
            weapon=str(weapon_iid) if weapon_iid else None,
            source=attack.source,
        )
    if killed_flag:
        if isinstance(state, MutableMapping) and isinstance(active, MutableMapping):
            _handle_player_death(monster, ctx, state, active, bus)
    return True


def _should_wake(
    monster: Mapping[str, Any] | None,
    event: str,
    rng: random.Random,
    config: CombatConfig,
) -> bool:
    from mutants.services.monster_ai import wake as wake_mod

    return wake_mod.should_wake(monster, event, rng, config)


_ENTRY_DEFAULT_CONFIG = CombatConfig()


def roll_entry_target(
    monster: MutableMapping[str, Any],
    player_state: Mapping[str, Any] | None,
    rng: random.Random,
    *,
    config: CombatConfig | None = None,
) -> Dict[str, Any]:
    try:
        state, active = pstate.get_active_pair(player_state)
    except Exception:
        state, active = pstate.get_active_pair()

    if not isinstance(monster, MutableMapping):
        return {"ok": False, "target_set": False, "taunt": None, "woke": False}

    player_id = _sanitize_player_id(
        active.get("id") if isinstance(active, Mapping) else None
    )
    if player_id is None and isinstance(state, Mapping):
        player_id = _sanitize_player_id(state.get("active_id"))
    if player_id is None:
        return {"ok": False, "target_set": False, "taunt": None, "woke": False}

    monster_hp = monster.get("hp")
    if isinstance(monster_hp, Mapping):
        try:
            if int(monster_hp.get("current", 0)) <= 0:
                return {"ok": True, "target_set": False, "taunt": None, "woke": False}
        except (TypeError, ValueError):
            pass

    if isinstance(state, Mapping) and isinstance(active, Mapping):
        player_pos = _normalize_player_pos(state, active)
    else:
        player_pos = None
    monster_pos = combat_loot.coerce_pos(monster.get("pos"))
    if player_pos is not None and monster_pos is not None and monster_pos != player_pos:
        return {"ok": True, "target_set": False, "taunt": None, "woke": False}

    previous = _sanitize_player_id(monster.get("target_player_id"))
    if previous == player_id:
        return {"ok": True, "target_set": False, "taunt": None, "woke": True}

    config_obj = config if isinstance(config, CombatConfig) else _ENTRY_DEFAULT_CONFIG
    woke = _should_wake(monster, "ENTRY", rng, config_obj)
    if not woke:
        return {"ok": True, "target_set": False, "taunt": None, "woke": False}

    monster["target_player_id"] = player_id

    raw_taunt = monster.get("taunt")
    taunt = raw_taunt.strip() if isinstance(raw_taunt, str) else None
    taunt = taunt or None

    return {"ok": True, "target_set": True, "taunt": taunt, "woke": True}


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
        item_id = _resolve_item_id(inst)
        if _is_broken_placeholder(item_id):
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
    origin_token = ORIGIN_WORLD
    if isinstance(best_inst, MutableMapping):
        best_inst["origin"] = origin_token
    actual_inst = itemsreg.get_instance(iid_str)
    if isinstance(actual_inst, MutableMapping):
        actual_inst["origin"] = origin_token
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
    turnlog.emit(
        ctx,
        "AI/ACT/PICKUP",
        monster=_monster_id(monster),
        iid=iid_str,
        item_id=entry.get("item_id"),
        item_name=name,
        origin=entry.get("origin"),
    )
    return {"ok": True, "iid": iid_str, "item_id": entry.get("item_id"), "item_name": name}


def _convert_item(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
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
        if not isinstance(iid, str):
            continue
        origin = entry.get("origin")
        if not isinstance(origin, str) or origin.strip().lower() != ORIGIN_WORLD:
            continue
        if iid not in tracked:
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
    itemsreg.remove_instance(iid)
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
    turnlog.emit(
        ctx,
        "AI/ACT/CONVERT",
        monster=_monster_id(monster),
        iid=iid,
        item_id=best_entry.get("item_id"),
        ions=best_value,
    )
    turnlog.emit(
        ctx,
        "ITEM/CONVERT",
        owner="monster",
        owner_id=_monster_id(monster),
        iid=iid,
        item_id=best_entry.get("item_id"),
        ions=best_value,
        source="monster",
    )
    return {"ok": True, "iid": iid, "item_id": best_entry.get("item_id"), "ions": best_value}


def _remove_broken_armour(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
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
    turnlog.emit(
        ctx,
        "AI/ACT/REMOVE_ARMOUR",
        monster=_monster_id(monster),
    )
    return {"ok": True}


def _heal_action(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
    if not isinstance(monster, MutableMapping):
        return {"ok": False, "reason": "invalid_monster"}

    config = ctx.get("combat_config") if isinstance(ctx, Mapping) else None
    if not isinstance(config, CombatConfig):
        config = CombatConfig()

    current_hp, max_hp = _sanitize_hp_block(monster.get("hp"))
    missing_hp = max(0, max_hp - current_hp)
    if missing_hp <= 0:
        return {"ok": False, "reason": "full_health"}

    heal_cost = heal_mod.heal_cost(monster, config)
    ledger = _ledger_state(monster)
    ions_available = max(0, _coerce_int(ledger.get("ions"), 0))
    if ions_available < heal_cost:
        return {
            "ok": False,
            "reason": "insufficient_ions",
            "required": heal_cost,
            "available": ions_available,
        }

    heal_points = heal_mod.heal_amount(monster)
    if heal_points <= 0:
        return {"ok": False, "reason": "no_heal_amount"}

    applied = min(heal_points, missing_hp)
    new_hp = min(max_hp, current_hp + applied)

    hp_block = monster.get("hp")
    if isinstance(hp_block, MutableMapping):
        hp_block["current"] = new_hp
        hp_block["max"] = max_hp
    else:
        monster["hp"] = {"current": new_hp, "max": max_hp}

    ledger["ions"] = max(0, ions_available - heal_cost)
    monster["ions"] = ledger["ions"]

    _refresh_monster(monster)
    _mark_monsters_dirty(ctx)

    label = _monster_display_name(monster)
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", f"{label}'s body is glowing!")

    turnlog.emit(
        ctx,
        "AI/ACT/HEAL",
        monster=_monster_id(monster),
        hp_restored=applied,
        ions_spent=heal_cost,
    )
    turnlog.emit(
        ctx,
        "COMBAT/HEAL",
        actor="monster",
        actor_id=_monster_id(monster),
        hp_restored=applied,
        ions_spent=heal_cost,
    )

    return {
        "ok": True,
        "healed": applied,
        "cost": heal_cost,
        "remaining_ions": monster.get("ions", 0),
        "hp": {"current": new_hp, "max": max_hp},
    }


_EMOTE_LINES: tuple[str, ...] = (
    "{monster} is looking awfully sad.",
    "{monster} is singing a strange song.",
    "{monster} is making strange noises.",
    "{monster} looks at you.",
    "{monster} pleads with you.",
    "{monster} is trying to make friends with you.",
    "{monster} is wondering what you're doing.",
)


def _flee_stub(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
    turnlog.emit(
        ctx,
        "AI/ACT/FLEE",
        monster=_monster_id(monster),
        reason="stub",
    )
    return {"ok": True, "fled": False}


def _cast_action(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
    if not isinstance(monster, MutableMapping):
        return {"ok": False, "reason": "invalid_monster"}

    cast_result = casting_mod.try_cast(monster, ctx)

    payload: dict[str, Any] = {
        "ok": cast_result.success,
        "cast": cast_result.success,
        "cost": cast_result.cost,
        "remaining_ions": cast_result.remaining_ions,
        "roll": cast_result.roll,
        "threshold": cast_result.threshold,
        "effect": cast_result.effect,
    }
    if cast_result.reason:
        payload["reason"] = cast_result.reason

    label = _monster_display_name(monster)
    bus = _feedback_bus(ctx)
    if cast_result.reason == "insufficient_ions":
        return payload

    if hasattr(bus, "push"):
        if cast_result.success:
            bus.push("COMBAT/INFO", f"{label} unleashes crackling energy!")
        else:
            bus.push("COMBAT/INFO", f"{label}'s spell fizzles out.")

    _refresh_monster(monster)
    _mark_monsters_dirty(ctx)

    turnlog.emit(
        ctx,
        "AI/ACT/CAST",
        monster=_monster_id(monster),
        success=cast_result.success,
        ions_spent=cast_result.cost,
        roll=cast_result.roll,
        threshold=cast_result.threshold,
    )
    turnlog.emit(
        ctx,
        "COMBAT/CAST",
        actor="monster",
        actor_id=_monster_id(monster),
        success=cast_result.success,
        ions_spent=cast_result.cost,
        effect=cast_result.effect,
    )

    return payload


def _emote_stub(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
    if not _EMOTE_LINES:
        return {"ok": False}
    if hasattr(rng, "randrange"):
        try:
            index = int(rng.randrange(len(_EMOTE_LINES)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            index = 0
    else:  # pragma: no cover - defensive
        index = 0
    index = max(0, min(len(_EMOTE_LINES) - 1, index))
    template = _EMOTE_LINES[index]
    message = template.format(monster=_monster_display_name(monster))
    bus = _feedback_bus(ctx)
    if hasattr(bus, "push"):
        bus.push("COMBAT/INFO", message)
    turnlog.emit(
        ctx,
        "AI/ACT/EMOTE",
        monster=_monster_id(monster),
        index=index,
        message=message,
    )
    return {"ok": True, "message": message, "index": index}


def _idle_stub(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Any:
    turnlog.emit(
        ctx,
        "AI/ACT/IDLE",
        monster=_monster_id(monster),
        reason="cascade-idle",
    )
    return {"ok": True}


_ACTION_TABLE: dict[str, ActionFn] = {
    "attack": _apply_player_damage,
    "pickup": _pickup_from_ground,
    "convert": _convert_item,
    "remove_armour": _remove_broken_armour,
    "heal": _heal_action,
    "flee": _flee_stub,
    "cast": _cast_action,
    "emote": _emote_stub,
    "idle": _idle_stub,
}

def execute_random_action(monster: Any, ctx: Any, *, rng: Any | None = None) -> None:
    if not isinstance(monster, MutableMapping):
        return None
    if not isinstance(ctx, MutableMapping):
        return None
    if rng is not None and hasattr(rng, "randrange"):
        random_obj = rng  # type: ignore[assignment]
    else:
        random_obj = random.Random()
    ctx["monster_ai_rng"] = random_obj
    inventory_mod.process_pending_drops(monster, ctx, random_obj)
    cascade_result = evaluate_cascade(monster, ctx)
    action_name = cascade_result.action
    if not action_name:
        return None
    action = _ACTION_TABLE.get(action_name)
    if not action:
        LOG.debug("No action handler for gate %s", cascade_result.gate)
        return None
    try:
        result = action(monster, ctx, random_obj)
        success = False
        payload: Dict[str, Any] = {}
        if isinstance(result, Mapping):
            payload = dict(result)
            success = bool(payload.get("ok", True))
        else:
            success = bool(result)
        if not success:
            payload.setdefault("monster", _monster_id(monster))
            payload.setdefault("success", False)
            turnlog.emit(ctx, f"AI/ACT/{action_name.upper()}", **payload)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Monster action %s failed", action_name)
    return None

