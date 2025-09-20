from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mutants.io.atomic import atomic_write_json
from . import items_catalog

DEFAULT_INSTANCES_PATH = "state/items/instances.json"
FALLBACK_INSTANCES_PATH = "state/instances.json"  # auto-fallback if the new path isn't used yet
CATALOG_PATH = "state/items/catalog.json"

LOG = logging.getLogger("mutants.itemsdbg")

BROKEN_WEAPON_ID = "broken_weapon"
BROKEN_ARMOUR_ID = "broken_armour"
_BROKEN_ITEM_IDS = {BROKEN_WEAPON_ID, BROKEN_ARMOUR_ID}


def _instance_id(inst: Dict[str, Any]) -> str:
    value = inst.get("iid") or inst.get("instance_id")
    return str(value) if value is not None else ""


def _item_id(inst: Dict[str, Any]) -> str:
    value = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
    return str(value) if value is not None else ""


def _sanitize_enchant_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 0
    return max(0, min(100, level))


def _sanitize_condition(value: Any) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        amount = 100
    return max(1, min(100, amount))


def _is_broken_item_id(item_id: str) -> bool:
    return item_id in _BROKEN_ITEM_IDS


def _normalize_instance(inst: Dict[str, Any]) -> bool:
    changed = False

    if not isinstance(inst, dict):
        return False

    iid = _instance_id(inst)
    if iid and inst.get("instance_id") != iid:
        inst["instance_id"] = iid
        changed = True
    if iid and inst.get("iid") != iid:
        inst["iid"] = iid
        changed = True

    level = _sanitize_enchant_level(inst.get("enchant_level"))
    if inst.get("enchant_level") != level:
        inst["enchant_level"] = level
        changed = True

    item_id = _item_id(inst)
    broken = _is_broken_item_id(item_id)

    if broken:
        if "condition" in inst:
            inst.pop("condition", None)
            changed = True
    else:
        condition = _sanitize_condition(inst.get("condition"))
        if inst.get("condition") != condition:
            inst["condition"] = condition
            changed = True

    return changed


def _normalize_instances(instances: Iterable[Dict[str, Any]]) -> bool:
    changed = False
    for inst in instances:
        if _normalize_instance(inst):
            changed = True
    return changed

class ItemsInstances:
    """
    Registry for altered (unique) item instances.
    - Stores a simple list of instance dicts.
    - Persists via atomic write when `save()` is called and state is dirty.
    """
    def __init__(self, path: str, items: List[Dict[str, Any]]):
        self._path = Path(path)
        normalized = _normalize_instances(items)
        self._items: List[Dict[str, Any]] = items
        self._by_id: Dict[str, Dict[str, Any]] = {it["instance_id"]: it for it in items if "instance_id" in it}
        self._dirty = normalized

    # ----- Queries -----

    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(instance_id)

    def list_for_item(self, item_id: str) -> Iterable[Dict[str, Any]]:
        return (it for it in self._items if it.get("item_id") == item_id)

    # ----- Mutations -----

    def _add(self, inst: Dict[str, Any]) -> Dict[str, Any]:
        _normalize_instance(inst)
        self._items.append(inst)
        self._by_id[inst["instance_id"]] = inst
        self._dirty = True
        return inst

    def create_instance(self, base_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new instance from a base catalog item.
        Seeds charges if base has charges_max; sets enchanted=no, wear=0 by default.
        """
        instance_id = f"{base_item['item_id']}#{uuid.uuid4().hex[:8]}"
        inst: Dict[str, Any] = {
            "instance_id": instance_id,
            "item_id": base_item["item_id"],
            "enchanted": "no",
            "wear": 0,
            "enchant_level": 0,
            "condition": 100,
        }
        charges_max = int(base_item.get("charges_max", 0) or 0)
        if charges_max > 0:
            inst["charges"] = charges_max
        # skull provenance fields (if ever needed) can be added by the loot system:
        # inst["skull_monster_type_id"] = "ghoul"; inst["skull_monster_name"] = "Ghoul"
        return self._add(inst)

    def apply_enchant(self, instance_id: str, level: int) -> Dict[str, Any]:
        inst = self._by_id[instance_id]
        inst["enchanted"] = "yes"
        inst["enchant_level"] = _sanitize_enchant_level(level)
        self._dirty = True
        return inst

    def apply_wear(self, instance_id: str, delta: int) -> Dict[str, Any]:
        inst = self._by_id[instance_id]
        inst["wear"] = max(0, int(inst.get("wear", 0)) + int(delta))
        self._dirty = True
        return inst

    def decrement_charges(self, instance_id: str, n: int = 1) -> Dict[str, Any]:
        inst = self._by_id[instance_id]
        inst["charges"] = max(0, int(inst.get("charges", 0)) - int(n))
        self._dirty = True
        return inst

    # ----- Persistence -----

    def save(self) -> None:
        if self._dirty:
            atomic_write_json(self._path, self._items)
            self._dirty = False


def load_instances(path: str = DEFAULT_INSTANCES_PATH) -> ItemsInstances:
    """
    Load instances from JSON.
    Supports either:
      - a list: [ {...}, {...} ]
      - or a dict with "instances": { "instances": [ ... ] }
    Falls back to `state/instances.json` if the default path is missing.
    """
    primary = Path(path)
    fallback = Path(FALLBACK_INSTANCES_PATH)
    target = primary if primary.exists() else (fallback if fallback.exists() else primary)

    if not target.exists():
        return ItemsInstances(str(target), [])

    with target.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []

    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    return ItemsInstances(str(target), items)


# ---------------------------------------------------------------------------
# lightweight read helpers --------------------------------------------------

def _load_instances_raw() -> List[Dict[str, Any]]:
    path = _instances_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    if not isinstance(items, list):
        return []

    seen: Dict[str, int] = {}
    duplicates: List[str] = []
    for inst in items:
        iid = str(inst.get("iid") or inst.get("instance_id") or "")
        if not iid:
            continue
        if iid in seen:
            duplicates.append(iid)
        else:
            seen[iid] = 1

    if duplicates:
        LOG.error(
            "[itemsdbg] DUPLICATE_IIDS_DETECTED count=%s sample=%s",
            len(duplicates),
            duplicates[:5],
        )

    _normalize_instances(items)

    return items


def _save_instances_raw(instances: List[Dict[str, Any]]) -> None:
    """Persist *instances* to disk preserving original JSON shape."""
    path = Path(DEFAULT_INSTANCES_PATH)
    try:
        with path.open("r", encoding="utf-8") as f:
            orig = json.load(f)
    except Exception:
        orig = []
    payload = {"instances": instances} if isinstance(orig, dict) and "instances" in orig else instances
    atomic_write_json(path, payload)
    invalidate_cache()


def _index_of(instances: List[Dict[str, Any]], iid: str) -> int:
    for idx, inst in enumerate(instances):
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            return idx
    raise KeyError(iid)


def charges_max_for(iid: str) -> int:
    """Return capacity for *iid* considering overrides."""
    inst = get_instance(iid) or {}
    tpl_id = inst.get("item_id")
    tpl = items_catalog.load_catalog().get(str(tpl_id)) if tpl_id else {}
    return int(inst.get("charges_max_override") or (tpl.get("charges_max") if tpl else 0) or 0)


def spend_charge(iid: str) -> bool:
    """Decrement charge by 1 if available. Returns True if spent."""
    raw = _load_instances_raw()
    try:
        idx = _index_of(raw, iid)
    except KeyError:
        return False
    inst = raw[idx]
    if int(inst.get("charges", 0)) < 1:
        return False
    inst["charges"] = int(inst.get("charges", 0)) - 1
    _save_instances_raw(raw)
    return True


def recharge_full(iid: str) -> int:
    """Recharge iid to full. Returns amount gained."""
    raw = _load_instances_raw()
    try:
        idx = _index_of(raw, iid)
    except KeyError:
        return 0
    inst = raw[idx]
    cap = charges_max_for(iid)
    before = int(inst.get("charges", 0))
    after = min(cap, before + (cap - before))
    inst["charges"] = after
    _save_instances_raw(raw)
    return after - before

def _pos_of(inst: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    if isinstance(inst.get("pos"), dict):
        p = inst["pos"]
        try:
            return int(p["year"]), int(p["x"]), int(p["y"])
        except Exception:
            pass
    try:
        return int(inst["year"]), int(inst["x"]), int(inst["y"])
    except Exception:
        return None


def _catalog() -> Dict[str, Any]:
    path = Path(CATALOG_PATH)
    if not path.exists():
        return {}
    try:
        data = json.load(path.open("r", encoding="utf-8"))
    except Exception:
        return {}
    return data.get("items", data) if isinstance(data, dict) else {}


def _display_name(item_id: str, cat: Dict[str, Any]) -> str:
    meta = cat.get(item_id)
    if isinstance(meta, dict):
        for key in ("name", "display_name", "title"):
            if isinstance(meta.get(key), str):
                return meta[key]
    return item_id


def list_at(year: int, x: int, y: int) -> List[str]:
    """
    Legacy helper: return display names for items at (year, x, y).
    Prefer ``list_ids_at`` for new code and apply display rules in the UI.
    """
    cat = _catalog()
    out: List[str] = []
    for inst in list_instances_at(year, x, y):
        item_id = (
            inst.get("item_id")
            or inst.get("catalog_id")
            or inst.get("id")
        )
        if item_id:
            out.append(_display_name(str(item_id), cat))
    return out


def list_ids_at(year: int, x: int, y: int) -> List[str]:
    """Return raw item_ids for instances at (year, x, y)."""
    out: List[str] = []
    for inst in list_instances_at(year, x, y):
        item_id = (
            inst.get("item_id")
            or inst.get("catalog_id")
            or inst.get("id")
        )
        if item_id:
            out.append(str(item_id))
    return out

# ---------------------------------------------------------------------------
# Extra helpers for ground/inventory transfers and caching

_CACHE: Optional[List[Dict[str, Any]]] = None
_CACHE_PATH: Optional[str] = None
_CACHE_MTIME: Optional[float] = None


def _instances_path() -> Path:
    primary = Path(DEFAULT_INSTANCES_PATH)
    if primary.exists():
        return primary
    fallback = Path(FALLBACK_INSTANCES_PATH)
    return fallback if fallback.exists() else primary


def _stat_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def invalidate_cache() -> None:
    """Clear the cached snapshot forcing the next read to hit disk."""
    global _CACHE, _CACHE_PATH, _CACHE_MTIME
    _CACHE = None
    _CACHE_PATH = None
    _CACHE_MTIME = None


def _cache() -> List[Dict[str, Any]]:
    global _CACHE, _CACHE_PATH, _CACHE_MTIME
    path = _instances_path()
    mtime = _stat_mtime(path)
    try:
        path_key = str(path.resolve())
    except Exception:
        path_key = str(path)

    if (
        _CACHE is None
        or _CACHE_PATH != path_key
        or _CACHE_MTIME is None
        or _CACHE_MTIME != mtime
    ):
        _CACHE = _load_instances_raw()
        _CACHE_PATH = path_key
        _CACHE_MTIME = mtime

    if _CACHE is not None:
        _normalize_instances(_CACHE)

    assert _CACHE is not None
    return _CACHE

def save_instances() -> None:
    """Persist the cached instances list back to disk."""
    data = _cache()
    _save_instances_raw(data)


def remove_instances(instance_ids: List[str]) -> int:
    """Remove all instances whose ids are in ``instance_ids``."""

    targets = {str(i) for i in instance_ids if i}
    if not targets:
        return 0

    raw = _cache()
    before = len(raw)

    def _iid(inst: Dict[str, Any]) -> Optional[str]:
        value = inst.get("iid") or inst.get("instance_id")
        return str(value) if value else None

    raw[:] = [inst for inst in raw if _iid(inst) not in targets]
    _save_instances_raw(raw)
    return before - len(raw)

def list_instances_at(year: int, x: int, y: int) -> List[Dict[str, Any]]:
    raw = _cache()
    out: List[Dict[str, Any]] = []
    tgt = (int(year), int(x), int(y))
    for inst in raw:
        pos = _pos_of(inst)
        if pos and pos == tgt:
            out.append(inst)
    return out

def get_instance(iid: str) -> Optional[Dict[str, Any]]:
    """Return the cached instance matching ``iid`` if present."""

    raw = _cache()
    siid = str(iid)
    for inst in raw:
        inst_id = str(inst.get("iid") or inst.get("instance_id") or "")
        if inst_id == siid:
            return inst
    return None


def delete_instance(iid: str) -> int:
    """Remove the instance identified by ``iid`` from the cache and persist."""

    raw = _cache()
    siid = str(iid)
    before = len(raw)
    raw[:] = [inst for inst in raw if str(inst.get("iid") or inst.get("instance_id") or "") != siid]
    removed = before - len(raw)
    _save_instances_raw(raw)
    return removed


def get_enchant_level(iid: str) -> int:
    inst = get_instance(iid)
    if not inst:
        return 0
    level = _sanitize_enchant_level(inst.get("enchant_level"))
    if inst.get("enchant_level") != level:
        inst["enchant_level"] = level
    return level


def is_enchanted(iid: str) -> bool:
    inst = get_instance(iid)
    if not inst:
        return False
    enchanted_flag = inst.get("enchanted")
    if isinstance(enchanted_flag, str) and enchanted_flag.lower() == "yes":
        return True
    return get_enchant_level(iid) > 0


def _is_broken_instance(inst: Dict[str, Any]) -> bool:
    return _is_broken_item_id(_item_id(inst))


def get_condition(iid: str) -> int:
    inst = get_instance(iid)
    if not inst:
        return 0
    if _is_broken_instance(inst):
        inst.pop("condition", None)
        return 0
    condition = _sanitize_condition(inst.get("condition"))
    if inst.get("condition") != condition:
        inst["condition"] = condition
    return condition


def set_condition(iid: str, value: int) -> int:
    inst = get_instance(iid)
    if not inst:
        raise KeyError(iid)
    if is_enchanted(iid):
        return get_condition(iid)
    if _is_broken_instance(inst):
        inst.pop("condition", None)
        return 0
    amount = _sanitize_condition(value)
    inst["condition"] = amount
    return amount


def crack_instance(iid: str) -> Optional[Dict[str, Any]]:
    inst = get_instance(iid)
    if not inst:
        return None

    current_item_id = _item_id(inst)
    catalog = items_catalog.load_catalog()
    tpl = catalog.get(current_item_id) if catalog else None
    is_armour = bool(tpl.get("armour")) if isinstance(tpl, dict) else False
    inst["item_id"] = BROKEN_ARMOUR_ID if is_armour else BROKEN_WEAPON_ID
    inst.pop("condition", None)
    _normalize_instance(inst)
    return inst


def snapshot_instances() -> List[Dict[str, Any]]:
    """Return a shallow copy of the cached instances list."""

    return [inst.copy() for inst in _cache()]


def clear_position(iid: str) -> None:
    """Back-compat: clear by iid (may hit wrong object if duplicate iids exist)."""

    raw = _cache()
    for inst in raw:
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            inst.pop("pos", None)
            inst["year"] = -1
            inst["x"] = -1
            inst["y"] = -1
            break
    _save_instances_raw(raw)


def clear_position_at(iid: str, year: int, x: int, y: int) -> bool:
    """Preferred: clear only if the iid currently resides at (year, x, y)."""

    raw = _cache()
    target = (int(year), int(x), int(y))
    for inst in raw:
        inst_id = inst.get("iid") or inst.get("instance_id")
        if not (inst_id and str(inst_id) == str(iid)):
            continue

        pos = inst.get("pos") or {}
        current = (
            int(pos.get("year", inst.get("year", -2))),
            int(pos.get("x", inst.get("x", 99999))),
            int(pos.get("y", inst.get("y", 99999))),
        )
        if current == target:
            inst.pop("pos", None)
            inst["year"] = -1
            inst["x"] = -1
            inst["y"] = -1
            _save_instances_raw(raw)
            return True

    LOG.error(
        "[itemsdbg] CLEAR_AT_MISS iid=%s not at (%s,%s,%s); no change",
        iid,
        year,
        x,
        y,
    )
    return False

def set_position(iid: str, year: int, x: int, y: int) -> None:
    raw = _cache()
    for inst in raw:
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            inst["pos"] = {"year": int(year), "x": int(x), "y": int(y)}
            inst["year"] = int(year)
            inst["x"] = int(x)
            inst["y"] = int(y)
            break


def create_and_save_instance(item_id: str, year: int, x: int, y: int, origin: str = "debug_add") -> str:
    """Create a new instance at (year,x,y) and persist it. Returns iid."""
    raw = _cache()
    seq = len(raw) + 1
    iid = f"dbg_{year}_{x}_{y}_{seq}"
    inst = {
        "iid": iid,
        "item_id": str(item_id),
        "pos": {"year": int(year), "x": int(x), "y": int(y)},
        "year": int(year),
        "x": int(x),
        "y": int(y),
        "origin": origin,
        "enchant_level": 0,
        "condition": 100,
    }
    cat = items_catalog.load_catalog()
    tpl = cat.get(str(item_id)) if cat else None
    if tpl and int(tpl.get("charges_max", 0) or 0) > 0:
        inst["charges"] = int(tpl.get("charges_max"))
    _normalize_instance(inst)
    raw.append(inst)
    _save_instances_raw(raw)
    return iid

