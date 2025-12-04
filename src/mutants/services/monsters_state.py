from __future__ import annotations

import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from mutants.registries import items_catalog
from mutants.registries import items_instances
from mutants.registries import monsters_instances
from mutants.services import items_weight
from mutants.services import player_state as pstate
from mutants.services import state_debug
from mutants.state import state_path

LOG = logging.getLogger(__name__)


def _looks_like_instance_id(s: Any) -> bool:
    """Treat only strings prefixed with ``i.`` as real instance ids."""

    return isinstance(s, str) and s.startswith("i.")

DEFAULT_MONSTERS_PATH = state_path("monsters", "instances.json")


def _sanitize_int(value: Any, *, minimum: int = 0, maximum: Optional[int] = None, fallback: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = fallback
    if maximum is not None:
        result = min(maximum, result)
    return max(minimum, result)


def _sanitize_stats(payload: Mapping[str, Any] | None) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for key in ("str", "dex", "con", "int", "wis", "cha"):
        stats[key] = _sanitize_int(payload.get(key) if isinstance(payload, Mapping) else None, fallback=0)
    return stats


def _sanitize_hp(payload: Mapping[str, Any] | None) -> Dict[str, int]:
    cur = _sanitize_int(payload.get("current") if isinstance(payload, Mapping) else None, minimum=0, fallback=0)
    cap = _sanitize_int(payload.get("max") if isinstance(payload, Mapping) else None, minimum=1, fallback=max(cur, 1))
    cur = min(cur, cap)
    return {"current": cur, "max": cap}


def _sanitize_ready_target(value: Any) -> Optional[str]:
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


def _dedup_ints(values: Iterable[Any]) -> List[int]:
    deduped: List[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if year not in seen:
            seen.add(year)
            deduped.append(year)
    return deduped


def _sanitize_pos(value: Any) -> Optional[List[int]]:
    if isinstance(value, Mapping):
        coords = [value.get("year"), value.get("x"), value.get("y")]
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        coords = list(value)
    else:
        return None
    if len(coords) != 3:
        return None
    out: List[int] = []
    for coord in coords:
        try:
            out.append(int(coord))
        except (TypeError, ValueError):
            return None
    return out


def _normalize_notes(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _sanitize_status_entry(payload: Any) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        raw_id = payload.get("status_id") or payload.get("id")
        if isinstance(raw_id, str):
            status_id = raw_id.strip()
        elif raw_id is None:
            status_id = None
        else:
            status_id = str(raw_id).strip()
        if not status_id:
            return None
        try:
            duration_raw = payload.get("duration")
            if duration_raw is None:
                duration_raw = payload.get("turns")
            duration = int(duration_raw)
        except (TypeError, ValueError):
            duration = 0
        return {"status_id": status_id, "duration": max(0, duration)}
    if isinstance(payload, str):
        status_id = payload.strip()
        if not status_id:
            return None
        return {"status_id": status_id, "duration": 0}
    return None


def _sanitize_status_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        entries: List[Dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for item in payload:
            sanitized = _sanitize_status_entry(item)
            if not sanitized:
                continue
            key = (sanitized["status_id"], sanitized["duration"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(sanitized)
        return entries
    sanitized = _sanitize_status_entry(payload)
    return [sanitized] if sanitized else []


def _mint_iid(monster_id: str, item_id: str, *, seen: set[str]) -> str:
    return items_instances.mint_iid(seen=seen)


def _coerce_template(catalog: Mapping[str, Any] | None, item_id: str) -> Mapping[str, Any]:
    if not isinstance(catalog, Mapping):
        return {}
    meta = catalog.get(item_id)
    if isinstance(meta, Mapping):
        return meta
    return {}


def _normalize_tags(value: Any) -> List[str]:
    if isinstance(value, list):
        tags = []
        for item in value:
            if isinstance(item, str) and item:
                tags.append(item)
        return tags
    if isinstance(value, str) and value:
        return [value]
    return []


def _ensure_ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    state_payload = monster.get("_ai_state")
    if isinstance(state_payload, MutableMapping):
        state = state_payload
    elif isinstance(state_payload, Mapping):
        state = dict(state_payload)
        monster["_ai_state"] = state
    else:
        state = {}
        monster["_ai_state"] = state

    json_payload = monster.get("ai_state_json")
    if isinstance(json_payload, str) and json_payload.strip():
        try:
            decoded = json.loads(json_payload)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, Mapping):
            for key, value in decoded.items():
                state.setdefault(key, value)

    ledger_payload = state.get("ledger")
    if isinstance(ledger_payload, MutableMapping):
        ledger = ledger_payload
    elif isinstance(ledger_payload, Mapping):
        ledger = dict(ledger_payload)
        state["ledger"] = ledger
    else:
        ledger = {}
        state["ledger"] = ledger

    top_ions_present = "ions" in monster
    top_riblets_present = "riblets" in monster
    top_ions = _sanitize_int(monster.get("ions"), minimum=0, fallback=0)
    top_riblets = _sanitize_int(monster.get("riblets"), minimum=0, fallback=0)
    ledger_ions = _sanitize_int(ledger.get("ions"), minimum=0, fallback=0)
    ledger_riblets = _sanitize_int(ledger.get("riblets"), minimum=0, fallback=0)

    if top_ions_present:
        ledger_ions = top_ions
    else:
        top_ions = ledger_ions
    if top_riblets_present:
        ledger_riblets = top_riblets
    else:
        top_riblets = ledger_riblets

    ledger["ions"] = ledger_ions
    ledger["riblets"] = ledger_riblets
    monster["ions"] = top_ions
    monster["riblets"] = top_riblets
    monster["_ai_state"] = state
    return state


def _encode_ai_state(state: Mapping[str, Any]) -> Optional[str]:
    if not isinstance(state, Mapping) or not state:
        return None
    try:
        return json.dumps(state, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        fallback: Dict[str, Any] = {}
        ledger_payload = state.get("ledger") if isinstance(state, Mapping) else None
        if isinstance(ledger_payload, Mapping):
            fallback["ledger"] = {
                "ions": _sanitize_int(ledger_payload.get("ions"), minimum=0, fallback=0),
                "riblets": _sanitize_int(ledger_payload.get("riblets"), minimum=0, fallback=0),
            }
        if not fallback:
            return None
        return json.dumps(fallback, sort_keys=True, separators=(",", ":"))


def _normalize_item(
    item: MutableMapping[str, Any] | None,
    *,
    monster_id: str,
    seen_iids: set[str],
    catalog: Mapping[str, Any] | None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, MutableMapping):
        return None

    changed = False
    sanitized: Dict[str, Any] = {}

    raw_item_id = item.get("item_id") or item.get("id") or item.get("catalog_id")
    if not raw_item_id:
        # Armour payloads created during monster spawning only carry an instance id.
        iid_lookup = item.get("iid") or item.get("instance_id")
        if iid_lookup:
            inst = items_instances.get_instance(str(iid_lookup))
            if isinstance(inst, Mapping):
                raw_item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")

    item_id = str(raw_item_id) if raw_item_id else ""
    if not item_id:
        return None
    sanitized["item_id"] = item_id

    enchant_level = _sanitize_int(item.get("enchant_level"), minimum=0, fallback=0)
    if item.get("enchant_level") != enchant_level:
        changed = True
    sanitized["enchant_level"] = enchant_level

    condition_min = 100 if enchant_level > 0 else 1
    default_condition = 100 if enchant_level > 0 else 100
    condition = _sanitize_int(item.get("condition"), minimum=condition_min, maximum=100, fallback=default_condition)
    if condition != item.get("condition"):
        changed = True
    sanitized["condition"] = condition

    iid_raw = item.get("iid") or item.get("instance_id")
    iid = str(iid_raw) if iid_raw else ""
    if iid and iid not in seen_iids:
        seen_iids.add(iid)
    if not iid:
        iid = _mint_iid(monster_id, item_id, seen=seen_iids)
        changed = True
    sanitized["iid"] = iid

    origin_raw = item.get("origin")
    if isinstance(origin_raw, str):
        origin_token = origin_raw.strip().lower()
    else:
        origin_token = ""
    if not origin_token:
        origin_token = "native"
    if origin_raw != origin_token:
        changed = True
    sanitized["origin"] = origin_token

    tags = _normalize_tags(item.get("tags"))
    if tags:
        sanitized["tags"] = tags

    notes = _normalize_notes(item.get("notes"))
    if notes:
        sanitized["notes"] = notes

    template = _coerce_template(catalog, item_id)
    derived: Dict[str, Any] = {}

    effective_weight = items_weight.get_effective_weight(sanitized, template)
    derived["effective_weight"] = effective_weight

    if template.get("armour"):
        base_ac = _sanitize_int(template.get("armour_class"), minimum=0, fallback=0)
        derived["armour_class"] = base_ac + enchant_level

    if template.get("ranged"):
        derived["is_ranged"] = True

    for key in ("base_power_melee", "base_power"):
        if key in template:
            base_power = _sanitize_int(template.get(key), minimum=0, fallback=0)
            derived["base_damage"] = base_power + (4 * enchant_level)
            break

    derived["can_degrade"] = enchant_level == 0 and not bool(template.get("nondegradable"))

    if derived:
        sanitized["derived"] = derived

    if changed:
        item.clear()
        item.update(sanitized)
    else:
        item.update(sanitized)

    return sanitized


def _collect_bag_entries(
    monster: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any] | None,
    seen_iids: set[str],
) -> List[Dict[str, Any]]:
    monster_id = (
        str(monster.get("id"))
        or str(monster.get("instance_id") or "")
        or str(monster.get("monster_id") or "")
    )

    bag_payload: list[Any] = []

    def _coerce_entry(raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, Mapping):
            entry: Dict[str, Any] = dict(raw)
        elif isinstance(raw, str):
            if _looks_like_instance_id(raw):
                entry = {"iid": raw}
            else:
                entry = {"item_id": raw}
        else:
            return None

        if entry.get("instance_id") and not entry.get("iid"):
            entry["iid"] = entry.get("instance_id")

        if entry.get("iid") and not entry.get("item_id"):
            inst = items_instances.get_instance(entry.get("iid"))
            if isinstance(inst, Mapping):
                item_id = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
                if item_id:
                    entry["item_id"] = str(item_id)
            elif not _looks_like_instance_id(entry.get("iid")):
                entry["item_id"] = str(entry["iid"])

        return entry

    existing_iids: set[str] = set()
    bag_entries = monster.get("bag")
    if isinstance(bag_entries, list):
        for raw in bag_entries:
            entry = _coerce_entry(raw)
            if not entry:
                continue
            if entry.get("iid"):
                existing_iids.add(str(entry["iid"]))
            bag_payload.append(entry)

    inventory_payload = monster.get("inventory")
    if isinstance(inventory_payload, list):
        for raw in inventory_payload:
            entry = _coerce_entry(raw)
            if not entry:
                continue
            entry_iid = str(entry.get("iid")) if entry.get("iid") else None
            if entry_iid and entry_iid in existing_iids:
                continue
            if entry_iid:
                existing_iids.add(entry_iid)
            bag_payload.append(entry)

    bag = _resolve_bag(
        bag_payload,
        monster_id=monster_id,
        seen_iids=seen_iids,
        catalog=catalog,
    )

    return bag


def _resolve_bag(
    bag: Iterable[Any] | None,
    *,
    monster_id: str,
    seen_iids: set[str],
    catalog: Mapping[str, Any] | None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(bag, Iterable) or isinstance(bag, (str, bytes)):
        return normalized
    for item in bag:
        normalized_item = _normalize_item(item, monster_id=monster_id, seen_iids=seen_iids, catalog=catalog)
        if normalized_item:
            normalized.append(normalized_item)
    return normalized


def _resolve_armour_slot(
    payload: Any,
    *,
    monster_id: str,
    seen_iids: set[str],
    catalog: Mapping[str, Any] | None,
) -> Optional[Dict[str, Any]]:
    normalized = _normalize_item(payload, monster_id=monster_id, seen_iids=seen_iids, catalog=catalog)
    return normalized


def _resolve_wielded(
    value: Any,
    *,
    bag: List[Dict[str, Any]],
) -> Optional[str]:
    candidates = {item["iid"]: item for item in bag if isinstance(item, Mapping) and item.get("iid")}
    if not candidates:
        return None

    if isinstance(value, str) and value:
        if value in candidates:
            return value
        for item in bag:
            if value == item.get("item_id"):
                return item["iid"]

    return next(iter(candidates))


def _derive_armour_payload(
    armour: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(armour, Mapping):
        return None
    iid = armour.get("iid")
    if not iid:
        return None
    derived = armour.get("derived") if isinstance(armour.get("derived"), Mapping) else {}
    return {
        "iid": iid,
        "item_id": armour.get("item_id"),
        "armour_class": _sanitize_int(derived.get("armour_class"), minimum=0, fallback=0),
    }


def _derive_weapon_payload(
    weapon: Optional[Mapping[str, Any]],
    *,
    stats: Mapping[str, int],
) -> Optional[Dict[str, Any]]:
    if not isinstance(weapon, Mapping):
        return None
    iid = weapon.get("iid")
    if not iid:
        return None
    derived = weapon.get("derived") if isinstance(weapon.get("derived"), Mapping) else {}
    base_damage = _sanitize_int(derived.get("base_damage"), minimum=0, fallback=0)
    str_bonus = _sanitize_int(stats.get("str"), minimum=0, fallback=0) // 10
    total_damage = base_damage + str_bonus
    return {
        "iid": iid,
        "item_id": weapon.get("item_id"),
        "damage": total_damage,
        "base_damage": base_damage,
        "strength_bonus": str_bonus,
    }


def _compute_derived(
    *,
    stats: Mapping[str, int],
    armour_payload: Optional[Dict[str, Any]],
    weapon_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    dex_bonus = _sanitize_int(stats.get("dex"), minimum=0, fallback=0) // 10
    armour_ac = armour_payload["armour_class"] if armour_payload else 0
    strength_bonus = _sanitize_int(stats.get("str"), minimum=0, fallback=0) // 10
    weapon_damage = weapon_payload["damage"] if weapon_payload else strength_bonus

    derived: Dict[str, Any] = {
        "dex_bonus": dex_bonus,
        "str_bonus": strength_bonus,
        "armour_class": dex_bonus + armour_ac,
        "weapon_damage": weapon_damage,
    }
    if armour_payload:
        derived["armour"] = armour_payload
    if weapon_payload:
        derived["weapon"] = weapon_payload
    return derived


def _resolve_prefers_ranged_flag(monster: Mapping[str, Any]) -> bool:
    if not isinstance(monster, Mapping):
        return False
    raw = monster.get("prefers_ranged")
    if raw is not None:
        return bool(raw)
    state = monster.get("_ai_state") if isinstance(monster.get("_ai_state"), Mapping) else None
    if isinstance(state, Mapping):
        state_value = state.get("prefers_ranged")
        if state_value is not None:
            return bool(state_value)
    return False


def _armour_score(entry: Mapping[str, Any] | None) -> int:
    if not isinstance(entry, Mapping):
        return 0
    derived = entry.get("derived") if isinstance(entry.get("derived"), Mapping) else {}
    return _sanitize_int(derived.get("armour_class"), minimum=0, fallback=0)


def _weapon_candidate(
    entry: Mapping[str, Any],
    *,
    stats: Mapping[str, int],
) -> tuple[str, Dict[str, Any], bool] | None:
    if not isinstance(entry, Mapping):
        return None
    iid_raw = entry.get("iid")
    iid = str(iid_raw) if iid_raw else ""
    if not iid:
        return None
    payload = _derive_weapon_payload(entry, stats=stats)
    if not payload:
        return None
    derived = entry.get("derived") if isinstance(entry.get("derived"), Mapping) else {}
    is_ranged = bool(derived.get("is_ranged"))
    return iid, payload, is_ranged


def _auto_equip_armour(monster: MutableMapping[str, Any], bag: list[MutableMapping[str, Any]]) -> bool:
    if not isinstance(bag, list):
        return False
    current = monster.get("armour_slot") if isinstance(monster.get("armour_slot"), MutableMapping) else None
    current_score = _armour_score(current)

    best_index: int | None = None
    best_score = current_score

    for idx, entry in enumerate(bag):
        if not isinstance(entry, MutableMapping):
            continue
        score = _armour_score(entry)
        if score > best_score:
            best_score = score
            best_index = idx

    if best_index is None:
        return False

    best_entry = bag.pop(best_index)
    if isinstance(current, MutableMapping):
        bag.append(current)
    monster["armour_slot"] = best_entry
    return True


def _auto_equip_weapon(
    monster: MutableMapping[str, Any],
    bag: list[MutableMapping[str, Any]],
    *,
    stats: Mapping[str, int],
) -> bool:
    if not isinstance(bag, list):
        return False

    prefer_ranged = _resolve_prefers_ranged_flag(monster)
    current_iid = str(monster.get("wielded") or "")
    current_damage = 0
    current_is_ranged = False

    candidates: list[tuple[str, Dict[str, Any], bool]] = []

    for entry in bag:
        if not isinstance(entry, MutableMapping):
            continue
        candidate = _weapon_candidate(entry, stats=stats)
        if not candidate:
            continue
        iid, payload, is_ranged = candidate
        candidates.append(candidate)
        if iid == current_iid:
            current_damage = payload.get("damage", 0)
            current_is_ranged = is_ranged

    if prefer_ranged:
        ranged_candidates = [candidate for candidate in candidates if candidate[2]]
        if ranged_candidates:
            candidates = ranged_candidates
        elif current_is_ranged:
            # Current weapon is ranged but no other ranged candidates found.
            candidates = [candidate for candidate in candidates if candidate[0] == current_iid]

    if not candidates:
        return False

    best_iid = current_iid
    best_damage = current_damage

    for iid, payload, _ in candidates:
        damage = payload.get("damage", 0)
        if damage > best_damage:
            best_damage = damage
            best_iid = iid

    if not best_iid or best_iid == current_iid:
        return False

    monster["wielded"] = best_iid
    return True


def _auto_equip_upgrades(monster: MutableMapping[str, Any], *, stats: Mapping[str, int]) -> bool:
    bag_payload = monster.get("bag")
    if not isinstance(bag_payload, list):
        return False
    changed = False
    changed |= _auto_equip_armour(monster, bag_payload)
    changed |= _auto_equip_weapon(monster, bag_payload, stats=stats)
    return changed


def _refresh_monster_derived(monster: MutableMapping[str, Any]) -> None:
    stats = _sanitize_stats(monster.get("stats"))
    monster["stats"] = stats

    bag = monster.get("bag")
    if not isinstance(bag, list):
        bag = []
        monster["bag"] = bag

    equipment_changed = _auto_equip_upgrades(monster, stats=stats)

    armour = monster.get("armour_slot")
    armour_payload = _derive_armour_payload(armour)

    weapon_payload = None
    wielded = monster.get("wielded")
    if isinstance(bag, list) and wielded:
        for item in bag:
            if isinstance(item, Mapping) and item.get("iid") == wielded:
                weapon_payload = _derive_weapon_payload(item, stats=stats)
                break

    monster["derived"] = _compute_derived(
        stats=stats,
        armour_payload=armour_payload,
        weapon_payload=weapon_payload,
    )

    return equipment_changed


def _level_up_stats(stats: MutableMapping[str, int]) -> None:
    for key in ("str", "dex", "con", "int", "wis", "cha"):
        stats[key] = _sanitize_int(stats.get(key), fallback=0) + 10


def _level_up_hp(hp: MutableMapping[str, int]) -> None:
    payload = _sanitize_hp(hp)
    payload["max"] += 10
    payload["current"] = payload["max"]
    hp.clear()
    hp.update(payload)


def _apply_level_gain(monster: MutableMapping[str, Any]) -> None:
    current_level = _sanitize_int(monster.get("level"), minimum=1, fallback=1)
    monster["level"] = current_level + 1

    stats = monster.get("stats")
    if not isinstance(stats, MutableMapping):
        stats = {}
        monster["stats"] = stats
    _level_up_stats(stats)

    hp = monster.get("hp")
    if not isinstance(hp, MutableMapping):
        hp = {}
        monster["hp"] = hp
    _level_up_hp(hp)

    _refresh_monster_derived(monster)


class MonstersState:
    def __init__(
        self,
        path: Path,
        monsters: List[Dict[str, Any]],
        *,
        instances: Optional[monsters_instances.MonstersInstances] = None,
    ):
        self._path = path
        self._monsters = monsters
        self._by_id = {m["id"]: m for m in monsters if m.get("id")}
        self._dirty = False
        self._dirty_all = False
        self._dirty_ids: set[str] = set()
        self._deleted_ids: set[str] = set()
        self._last_accessed_id: Optional[str] = None
        self._instances = instances or monsters_instances.load_monsters_instances(path)

    def _prepare_store_payload(self, monster: Mapping[str, Any]) -> Dict[str, Any]:
        payload = copy.deepcopy(dict(monster))

        iid = payload.get("instance_id")
        if not _looks_like_instance_id(iid):
            # Not a persisted instance (likely a template-backed record) — skip persisting.
            raise KeyError("instance_id")
        payload["id"] = iid
        payload["instance_id"] = iid

        monster_kind = payload.get("monster_id")
        if monster_kind:
            payload["monster_id"] = str(monster_kind)
        else:
            payload["monster_id"] = str(payload.get("name") or monster_id)

        pos = _sanitize_pos(payload.get("pos")) or [0, 0, 0]
        payload["pos"] = pos

        payload["hp"] = _sanitize_hp(payload.get("hp"))

        state = _ensure_ai_state(payload)
        ai_state_json = _encode_ai_state(state)
        if ai_state_json is not None:
            payload["ai_state_json"] = ai_state_json
        else:
            payload.pop("ai_state_json", None)

        statuses = _sanitize_status_list(payload.get("status_effects"))
        payload["status_effects"] = [dict(entry) for entry in statuses]
        if statuses:
            payload["timers"] = [dict(entry) for entry in statuses]
        else:
            payload.pop("timers", None)

        return payload

    def _persist_monster(self, monster: Mapping[str, Any]) -> None:
        try:
            payload = self._prepare_store_payload(monster)
        except KeyError:
            return
        instance_id = payload["instance_id"]
        hp_block = payload.get("hp") if isinstance(payload.get("hp"), Mapping) else {}
        hp_cur = _sanitize_int(
            hp_block.get("current") if isinstance(hp_block, Mapping) else None,
            minimum=0,
            fallback=0,
        )
        hp_max = _sanitize_int(
            hp_block.get("max") if isinstance(hp_block, Mapping) else None,
            minimum=hp_cur,
            fallback=hp_cur,
        )
        pos = payload.get("pos") if isinstance(payload.get("pos"), list) else [0, 0, 0]
        year = _sanitize_int(pos[0] if len(pos) > 0 else None, fallback=0)
        x = _sanitize_int(pos[1] if len(pos) > 1 else None, fallback=0)
        y = _sanitize_int(pos[2] if len(pos) > 2 else None, fallback=0)

        fields = {
            "monster_id": payload.get("monster_id"),
            "year": year,
            "x": x,
            "y": y,
            "hp_cur": hp_cur,
            "hp_max": max(hp_cur, hp_max),
            "stats_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        }

        fields["ai_state_json"] = payload.get("ai_state_json")

        timers_payload = payload.get("status_effects") or []
        if timers_payload:
            fields["timers_json"] = json.dumps(
                {"status_effects": timers_payload},
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            fields["timers_json"] = None

        try:
            self._instances.update_fields(instance_id, **fields)
        except KeyError:
            if _looks_like_instance_id(instance_id):
                spawn_payload = copy.deepcopy(payload)
                spawn_payload.setdefault("hp", {"current": hp_cur, "max": max(hp_cur, hp_max)})
                self._instances.spawn(spawn_payload)
                try:
                    state_debug.log_monster_spawn(spawn_payload, reason="persist_spawn")
                except Exception:
                    pass

    def _sync_local_with_store(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for record in self._instances.list_all():
            if not isinstance(record, Mapping):
                continue
            entry = dict(record)
            state_block = _ensure_ai_state(entry)
            ai_state_json = _encode_ai_state(state_block)
            if ai_state_json is not None:
                entry["ai_state_json"] = ai_state_json
            else:
                entry.pop("ai_state_json", None)
            ident_raw = entry.get("id") or entry.get("instance_id") or entry.get("monster_id")
            ident = str(ident_raw) if ident_raw else ""
            if not ident:
                continue
            entry["instance_id"] = ident
            entry["id"] = ident
            assert entry["id"] == entry["instance_id"], "id must mirror instance_id"
            seen.add(ident)
            local = self._by_id.get(ident)
            if local is None:
                self._monsters.append(entry)
                self._by_id[ident] = entry
                local = entry
                try:
                    state_debug.log_monster_spawn(local, reason="store_sync")
                except Exception:
                    pass
            else:
                local.clear()
                local.update(entry)
            records.append(local)

        if not self._dirty and seen:
            for ident in list(self._by_id.keys()):
                if ident not in seen:
                    monster = self._by_id.pop(ident)
                    try:
                        self._monsters.remove(monster)
                    except ValueError:
                        pass
                    try:
                        state_debug.log_monster_despawn(monster, reason="store_removed")
                    except Exception:
                        pass

        return records

    def _track_dirty(self, monster_id: Optional[str], *, force_all: bool = False) -> None:
        self._dirty = True
        if force_all:
            self._dirty_all = True
            return
        if monster_id:
            self._dirty_ids.add(monster_id)
        else:
            self._dirty_all = True

    def list_all(self) -> List[Dict[str, Any]]:
        # Cache is the authoritative read path during a session.
        return list(self._monsters)

    def list_at(self, year: int, x: int, y: int) -> List[Dict[str, Any]]:
        def _match(mon: Dict[str, Any]) -> bool:
            pos = mon.get("pos")
            if not isinstance(pos, list) or len(pos) != 3:
                return False
            return int(pos[0]) == int(year) and int(pos[1]) == int(x) and int(pos[2]) == int(y)

        # Always read from the in-memory cache.
        raw = [mon for mon in self._monsters if _match(mon)]

        filtered: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for mon in raw:
            instance_id_raw = mon.get("instance_id")
            instance_id = str(instance_id_raw).strip() if instance_id_raw is not None else ""
            if not instance_id or instance_id in seen:
                continue
            seen.add(instance_id)
            filtered.append(mon)

        if len(filtered) != len(raw):
            LOG.warning(
                "[MonstersState.list_at %s,%s,%s] filtered %d -> %d",
                year,
                x,
                y,
                len(raw),
                len(filtered),
            )

        return filtered

    def get(self, monster_id: str) -> Optional[Dict[str, Any]]:
        # Do not reach into the store for reads; rely on cache.
        monster = self._by_id.get(monster_id)
        self._last_accessed_id = monster_id if monster else None
        return monster

    def add_instance(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Add a (template-derived) monster instance into the cached state,
        normalizing fields and marking the cache dirty so it will flush on the
        next end-of-command checkpoint.
        """

        normalized = normalize_records([dict(record)])
        if not normalized:
            raise ValueError("invalid monster record")

        entry = normalized[0]
        iid_raw = entry.get("instance_id") or entry.get("id")
        iid = str(iid_raw) if iid_raw else ""
        if not iid:
            raise KeyError("instance_id")

        self._by_id[iid] = entry
        replaced = False
        for idx, mon in enumerate(self._monsters):
            if isinstance(mon, Mapping) and (
                mon.get("instance_id") == iid or mon.get("id") == iid
            ):
                self._monsters[idx] = entry
                replaced = True
                break
        if not replaced:
            self._monsters.append(entry)

        self._track_dirty(iid)
        try:
            state_debug.log_monster_spawn(entry, reason="cache_add")
        except Exception:
            pass
        return entry

    def set_status_effects(
        self, monster_id: str, statuses: Iterable[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        monster = self._by_id.get(monster_id)
        if monster is None:
            raise KeyError(monster_id)

        raw_entries = list(statuses) if isinstance(statuses, Iterable) else []
        sanitized = _sanitize_status_list(raw_entries)
        current = _sanitize_status_list(monster.get("status_effects"))
        if current == sanitized:
            return [dict(entry) for entry in current]

        payload = [dict(entry) for entry in sanitized]
        monster["status_effects"] = payload
        if payload:
            monster["timers"] = [dict(entry) for entry in payload]
        else:
            monster.pop("timers", None)

        self._track_dirty(monster_id)
        return payload

    def decrement_status_effects(self, amount: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        if amount <= 0:
            return {}

        expired: Dict[str, List[Dict[str, Any]]] = {}
        changed = False

        for monster_id, monster in list(self._by_id.items()):
            entries = _sanitize_status_list(monster.get("status_effects"))
            updated: List[Dict[str, Any]] = []
            expired_entries: List[Dict[str, Any]] = []
            for entry in entries:
                remaining = max(0, int(entry.get("duration", 0)) - amount)
                if remaining > 0:
                    updated.append({"status_id": entry["status_id"], "duration": remaining})
                else:
                    expired_entries.append({"status_id": entry["status_id"], "duration": 0})
            if expired_entries:
                expired[monster_id] = expired_entries
            if updated != entries:
                changed = True
            self.set_status_effects(monster_id, updated)

        if changed:
            self.save()

        return expired

    def mark_dirty(self) -> None:
        self._track_dirty(self._last_accessed_id)

    def level_up_monster(self, monster_id: str) -> bool:
        monster = self._by_id.get(monster_id)
        if not monster:
            return False
        before_level = _sanitize_int(monster.get("level"), minimum=1, fallback=1)
        before_stats = _sanitize_stats(monster.get("stats"))
        before_hp = _sanitize_hp(monster.get("hp"))
        _apply_level_gain(monster)
        self._track_dirty(monster_id)
        if pstate._pdbg_enabled():  # pragma: no cover - diagnostic logging
            try:
                pstate._pdbg_setup_file_logging()
                after_level = _sanitize_int(monster.get("level"), minimum=1, fallback=before_level)
                delta_level = after_level - before_level
                after_stats = _sanitize_stats(monster.get("stats"))
                stat_tokens = []
                for key in ("str", "dex", "con", "int", "wis", "cha"):
                    delta = after_stats.get(key, 0) - before_stats.get(key, 0)
                    if delta:
                        stat_tokens.append(f"{key}:{delta:+d}")
                stats_summary = ",".join(stat_tokens) if stat_tokens else "none"
                after_hp = _sanitize_hp(monster.get("hp"))
                hp_delta = after_hp["max"] - before_hp["max"]
                LOG_P.info(
                    "[playersdbg] MON-LVL id=%s lvl=%s Δlvl=%+d stats=%s hp=%+d",
                    monster_id,
                    after_level,
                    delta_level,
                    stats_summary,
                    hp_delta,
                )
            except Exception:
                pass
        return True

    def kill_monster(self, monster_id: str) -> Dict[str, Any]:
        """Remove a monster from the state and return its dropped items."""

        monster = self._by_id.pop(monster_id, None)
        if not monster:
            return {"monster": None, "drops": [], "pos": None}

        try:
            catalog = items_catalog.load_catalog()
        except FileNotFoundError:
            catalog = {}

        monster["bag"] = _collect_bag_entries(monster, catalog=catalog, seen_iids=set())

        for idx, entry in enumerate(self._monsters):
            if entry is monster or entry.get("id") == monster_id:
                del self._monsters[idx]
                break

        drops: List[Dict[str, Any]] = []
        bag_items: List[Dict[str, Any]] = []
        bag = monster.get("bag")
        if isinstance(bag, list):
            for item in bag:
                if isinstance(item, Mapping):
                    entry = copy.deepcopy(item)
                    drops.append(entry)
                    bag_items.append(entry)

        armour = monster.get("armour_slot")
        armour_dropped = isinstance(armour, Mapping)
        if armour_dropped:
            armour_entry = copy.deepcopy(armour)
            drops.append(armour_entry)
        else:
            armour_entry = None

        monster["bag"] = []
        monster["armour_slot"] = None
        monster["wielded"] = None

        hp_block = monster.get("hp")
        if isinstance(hp_block, MutableMapping):
            hp_block["current"] = 0

        _refresh_monster_derived(monster)

        try:
            state_debug.log_monster_despawn(monster, reason="killed", drops=drops)
        except Exception:
            pass

        if pstate._pdbg_enabled():  # pragma: no cover - diagnostic logging
            try:
                pstate._pdbg_setup_file_logging()
                LOG_P.info(
                    "[playersdbg] MON-KILL id=%s pos=%s drops=%s bag=%s armour=%s",
                    monster_id,
                    monster.get("pos"),
                    len(drops),
                    len(bag_items),
                    "yes" if armour_dropped else "no",
                )
            except Exception:
                pass

        try:
            pstate.clear_ready_target_for(monster_id, reason="monster-dead")
        except Exception:
            pass

        self._track_dirty(monster_id)
        self._deleted_ids.add(monster_id)
        self._dirty_ids.discard(monster_id)
        self._last_accessed_id = None
        return {
            "monster": monster,
            "drops": drops,
            "pos": monster.get("pos"),
            "bag_drops": bag_items,
            "armour_drop": armour_entry,
        }

    def save(self) -> None:
        if not (self._dirty or self._deleted_ids):
            return

        if self._dirty_all:
            targets = [monster for monster in self._monsters if isinstance(monster, Mapping)]
        else:
            targets = [
                self._by_id[monster_id]
                for monster_id in self._dirty_ids
                if monster_id in self._by_id
            ]

        for monster in targets:
            try:
                self._persist_monster(monster)
            except Exception:
                LOG.exception("Failed to persist monster state")

        for monster_id in list(self._deleted_ids):
            try:
                self._instances.delete(monster_id)
            except KeyError:
                continue
            except Exception:
                LOG.exception("Failed to delete monster %s from store", monster_id)

        self._dirty = False
        self._dirty_all = False
        self._dirty_ids.clear()
        self._deleted_ids.clear()


_CACHE: Optional[MonstersState] = None
_CACHE_PATH: Optional[Path] = None
_CACHE_SIGNATURE: Optional[str] = None


def _load_raw(
    path: Path,
    instances: monsters_instances.MonstersInstances,
) -> tuple[List[Dict[str, Any]], bool]:
    snapshot = instances.list_all()
    if snapshot:
        records = [dict(mon) for mon in snapshot if isinstance(mon, Mapping)]
        return records, True

    return [], False


def _compute_signature(records: Iterable[Mapping[str, Any]]) -> str:
    try:
        payload = json.dumps(list(records), sort_keys=True, separators=(",", ":"))
    except TypeError:
        payload = str(len(list(records)))
    return payload


def _normalize_monsters(monsters: List[Dict[str, Any]], *, catalog: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_iids: set[str] = set()
    for raw in monsters:
        monster = dict(raw)

        # Canonical identity: prefer per-spawn instance_id; mirror into id.
        primary_raw = (
            monster.get("instance_id") or monster.get("id") or monster.get("monster_id")
        )
        primary = str(primary_raw) if primary_raw else f"i.{uuid.uuid4().hex[:12]}"
        monster["instance_id"] = primary
        monster["id"] = primary
        monster["_template_id"] = monster.get("monster_id")
        assert monster["id"] == monster["instance_id"]

        name_raw = monster.get("name") or monster.get("monster_id") or primary
        monster["name"] = str(name_raw)

        monster["level"] = _sanitize_int(monster.get("level"), minimum=1, fallback=1)
        monster["stats"] = _sanitize_stats(monster.get("stats"))
        monster["hp"] = _sanitize_hp(monster.get("hp"))

        state_block = _ensure_ai_state(monster)
        ai_state_json = _encode_ai_state(state_block)
        if ai_state_json is not None:
            monster["ai_state_json"] = ai_state_json
        else:
            monster.pop("ai_state_json", None)

        bag = _collect_bag_entries(monster, catalog=catalog, seen_iids=seen_iids)
        monster["bag"] = bag

        armour_payload = monster.get("armour_slot")
        if not isinstance(armour_payload, Mapping):
            armour_wearing = monster.get("armour_wearing")
            if armour_wearing:
                if isinstance(armour_wearing, Mapping):
                    armour_payload = armour_wearing
                elif isinstance(armour_wearing, str):
                    armour_payload = {"iid": armour_wearing}
                    for entry in bag:
                        if armour_wearing in (entry.get("iid"), entry.get("item_id")):
                            armour_payload = dict(entry)
                            break

        armour = _resolve_armour_slot(
            armour_payload,
            monster_id=primary,
            seen_iids=seen_iids,
            catalog=catalog,
        )
        if armour:
            bag = [item for item in bag if item.get("iid") != armour.get("iid")]
            monster["bag"] = bag
        monster["armour_slot"] = armour

        wielded_iid = _resolve_wielded(monster.get("wielded"), bag=bag)
        monster["wielded"] = wielded_iid

        monster["pinned_years"] = _dedup_ints(monster.get("pinned_years") or [])
        pos = _sanitize_pos(monster.get("pos"))
        if pos:
            monster["pos"] = pos
        else:
            monster.pop("pos", None)

        notes = _normalize_notes(monster.get("notes"))
        if notes:
            monster["notes"] = notes
        elif "notes" in monster:
            monster.pop("notes", None)

        armour_payload = _derive_armour_payload(armour)
        weapon_payload = None
        if wielded_iid:
            for item in bag:
                if item.get("iid") == wielded_iid:
                    weapon_payload = _derive_weapon_payload(item, stats=monster["stats"])
                    break
        derived = _compute_derived(stats=monster["stats"], armour_payload=armour_payload, weapon_payload=weapon_payload)
        monster["derived"] = derived

        ready_target = _sanitize_ready_target(monster.get("ready_target"))
        legacy_target = _sanitize_ready_target(monster.get("target_monster_id"))
        final_target = ready_target or legacy_target
        if final_target:
            monster["ready_target"] = final_target
            monster["target_monster_id"] = final_target
        else:
            monster["ready_target"] = None
            if "target_monster_id" in monster:
                monster["target_monster_id"] = None

        timers_payload: Any = monster.get("status_effects")
        if timers_payload is None:
            timers_payload = monster.get("timers")
        if timers_payload is None:
            timers_payload = monster.get("statuses")
        if timers_payload is None:
            timers_raw = monster.get("timers_json")
            if isinstance(timers_raw, str) and timers_raw.strip():
                try:
                    decoded = json.loads(timers_raw)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, Mapping):
                    timers_payload = decoded.get("status_effects") or decoded.get("statuses")
                elif isinstance(decoded, list):
                    timers_payload = decoded
        statuses = _sanitize_status_list(timers_payload)
        if statuses:
            monster["status_effects"] = statuses
            monster["timers"] = statuses
        else:
            monster["status_effects"] = []
            if "timers" in monster:
                monster.pop("timers", None)

        normalized.append(monster)

    return normalized


def load_state(path: Path | str = DEFAULT_MONSTERS_PATH) -> MonstersState:
    global _CACHE, _CACHE_PATH, _CACHE_SIGNATURE

    path_obj = Path(path)
    instances = monsters_instances.load_monsters_instances(path_obj)
    raw, from_store = _load_raw(path_obj, instances)
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = {}

    normalized = _normalize_monsters(raw, catalog=catalog)
    signature = _compute_signature(normalized)

    if _CACHE and _CACHE_PATH == path_obj and _CACHE_SIGNATURE == signature:
        return _CACHE

    state = MonstersState(path_obj, normalized, instances=instances)

    if normalized != raw or not from_store:
        state._track_dirty(None, force_all=True)
        state.save()
        signature = _compute_signature(state._monsters)

    _CACHE = state
    _CACHE_PATH = path_obj
    _CACHE_SIGNATURE = signature
    return state


def invalidate_cache() -> None:
    global _CACHE, _CACHE_PATH, _CACHE_SIGNATURE
    _CACHE = None
    _CACHE_PATH = None
    _CACHE_SIGNATURE = None


def clear_all_targets(monsters: MonstersState | None = None) -> bool:
    """Remove any ``target_player_id`` bindings from monster instances.

    Returns ``True`` when at least one monster was modified.
    """

    try:
        state = monsters if monsters is not None else load_state()
    except Exception:
        return False

    cleared = False
    for record in state.list_all():
        if not isinstance(record, MutableMapping):
            continue
        if record.get("target_player_id") is None:
            continue
        record["target_player_id"] = None
        cleared = True
        try:
            state.mark_dirty()
        except Exception:
            try:
                state._track_dirty(str(record.get("id")))  # type: ignore[attr-defined]
            except Exception:
                pass

    if cleared:
        try:
            state.save()
        except Exception:
            pass

    return cleared


def normalize_records(
    records: Iterable[Mapping[str, Any]],
    *,
    catalog: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Normalize raw monster records using the same rules as ``load_state``.

    Parameters
    ----------
    records:
        Iterable of raw monster records (dict-like objects).
    catalog:
        Optional item catalog mapping used to derive armour/weapon payloads.
        If omitted the catalog will be loaded via ``items_catalog``.

    Returns
    -------
    list of dict
        Normalized monsters ready for persistence.
    """

    if catalog is None:
        try:
            catalog = items_catalog.load_catalog()
        except FileNotFoundError:
            catalog = {}

    return _normalize_monsters([dict(m) for m in records], catalog=catalog)
LOG_P = logging.getLogger("mutants.playersdbg")
