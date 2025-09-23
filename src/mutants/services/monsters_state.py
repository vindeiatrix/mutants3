from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from mutants.io.atomic import atomic_write_json
from mutants.registries import items_catalog
from mutants.services import items_weight

DEFAULT_MONSTERS_PATH = Path("state/monsters/instances.json")


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


def _mint_iid(monster_id: str, item_id: str, *, seen: set[str]) -> str:
    base = monster_id or "monster"
    suffix = item_id or "item"
    while True:
        token = f"{base}#{suffix}#{uuid.uuid4().hex[:8]}"
        if token not in seen:
            seen.add(token)
            return token


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

    if "base_power" in template:
        base_power = _sanitize_int(template.get("base_power"), minimum=0, fallback=0)
        derived["base_damage"] = base_power + (4 * enchant_level)

    derived["can_degrade"] = enchant_level == 0 and not bool(template.get("nondegradable"))

    if derived:
        sanitized["derived"] = derived

    if changed:
        item.clear()
        item.update(sanitized)
    else:
        item.update(sanitized)

    return sanitized


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


def _refresh_monster_derived(monster: MutableMapping[str, Any]) -> None:
    stats = _sanitize_stats(monster.get("stats"))
    monster["stats"] = stats

    bag = monster.get("bag")
    if not isinstance(bag, list):
        bag = []
        monster["bag"] = bag

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
    def __init__(self, path: Path, monsters: List[Dict[str, Any]]):
        self._path = path
        self._monsters = monsters
        self._by_id = {m["id"]: m for m in monsters if m.get("id")}
        self._dirty = False

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self._monsters)

    def list_at(self, year: int, x: int, y: int) -> List[Dict[str, Any]]:
        def _match(mon: Dict[str, Any]) -> bool:
            pos = mon.get("pos")
            if not isinstance(pos, list) or len(pos) != 3:
                return False
            return int(pos[0]) == int(year) and int(pos[1]) == int(x) and int(pos[2]) == int(y)

        return [mon for mon in self._monsters if _match(mon)]

    def get(self, monster_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(monster_id)

    def mark_dirty(self) -> None:
        self._dirty = True

    def level_up_monster(self, monster_id: str) -> bool:
        monster = self._by_id.get(monster_id)
        if not monster:
            return False
        _apply_level_gain(monster)
        self.mark_dirty()
        return True

    def kill_monster(self, monster_id: str) -> Dict[str, Any]:
        """Remove a monster from the state and return its dropped items."""

        monster = self._by_id.pop(monster_id, None)
        if not monster:
            return {"monster": None, "drops": [], "pos": None}

        for idx, entry in enumerate(self._monsters):
            if entry is monster or entry.get("id") == monster_id:
                del self._monsters[idx]
                break

        drops: List[Dict[str, Any]] = []
        bag = monster.get("bag")
        if isinstance(bag, list):
            for item in bag:
                if isinstance(item, Mapping):
                    drops.append(item)

        armour = monster.get("armour_slot")
        if isinstance(armour, Mapping):
            drops.append(armour)

        monster["bag"] = []
        monster["armour_slot"] = None
        monster["wielded"] = None

        hp_block = monster.get("hp")
        if isinstance(hp_block, MutableMapping):
            hp_block["current"] = 0

        _refresh_monster_derived(monster)

        self.mark_dirty()
        return {
            "monster": monster,
            "drops": drops,
            "pos": monster.get("pos"),
        }

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {"monsters": self._monsters}
        atomic_write_json(self._path, payload)
        self._dirty = False


_CACHE: Optional[MonstersState] = None
_CACHE_PATH: Optional[Path] = None
_CACHE_MTIME: Optional[float] = None


def _load_raw(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, Mapping) and "monsters" in data:
        monsters = data.get("monsters", [])
    elif isinstance(data, list):
        monsters = data
    else:
        monsters = []

    return [dict(mon) for mon in monsters if isinstance(mon, Mapping)]


def _normalize_monsters(monsters: List[Dict[str, Any]], *, catalog: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_iids: set[str] = set()
    for raw in monsters:
        monster = dict(raw)

        monster_id_raw = monster.get("id") or monster.get("monster_id") or monster.get("instance_id")
        monster_id = str(monster_id_raw) if monster_id_raw else f"monster#{uuid.uuid4().hex[:6]}"
        monster["id"] = monster_id

        name_raw = monster.get("name") or monster.get("monster_id") or monster_id
        monster["name"] = str(name_raw)

        monster["level"] = _sanitize_int(monster.get("level"), minimum=1, fallback=1)
        monster["stats"] = _sanitize_stats(monster.get("stats"))
        monster["hp"] = _sanitize_hp(monster.get("hp"))

        bag = _resolve_bag(monster.get("bag"), monster_id=monster_id, seen_iids=seen_iids, catalog=catalog)
        monster["bag"] = bag

        armour = _resolve_armour_slot(monster.get("armour_slot"), monster_id=monster_id, seen_iids=seen_iids, catalog=catalog)
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

        normalized.append(monster)

    return normalized


def _stat_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def load_state(path: Path | str = DEFAULT_MONSTERS_PATH) -> MonstersState:
    global _CACHE, _CACHE_PATH, _CACHE_MTIME

    path_obj = Path(path)
    mtime = _stat_mtime(path_obj)

    if _CACHE and _CACHE_PATH == path_obj and _CACHE_MTIME == mtime:
        return _CACHE

    raw = _load_raw(path_obj)
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = {}

    normalized = _normalize_monsters(raw, catalog=catalog)
    state = MonstersState(path_obj, normalized)

    if normalized != raw:
        state.mark_dirty()
        state.save()
        mtime = _stat_mtime(path_obj)

    _CACHE = state
    _CACHE_PATH = path_obj
    _CACHE_MTIME = mtime
    return state


def invalidate_cache() -> None:
    global _CACHE, _CACHE_PATH, _CACHE_MTIME
    _CACHE = None
    _CACHE_PATH = None
    _CACHE_MTIME = None


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
