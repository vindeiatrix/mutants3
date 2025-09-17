from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any, Tuple

from mutants.io.atomic import atomic_write_json
from . import items_catalog

DEFAULT_INSTANCES_PATH = "state/items/instances.json"
FALLBACK_INSTANCES_PATH = "state/instances.json"  # auto-fallback if the new path isn't used yet
CATALOG_PATH = "state/items/catalog.json"

class ItemsInstances:
    """
    Registry for altered (unique) item instances.
    - Stores a simple list of instance dicts.
    - Persists via atomic write when `save()` is called and state is dirty.
    """
    def __init__(self, path: str, items: List[Dict[str, Any]]):
        self._path = Path(path)
        self._items: List[Dict[str, Any]] = items
        self._by_id: Dict[str, Dict[str, Any]] = {it["instance_id"]: it for it in items if "instance_id" in it}
        self._dirty = False

    # ----- Queries -----

    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(instance_id)

    def list_for_item(self, item_id: str) -> Iterable[Dict[str, Any]]:
        return (it for it in self._items if it.get("item_id") == item_id)

    # ----- Mutations -----

    def _add(self, inst: Dict[str, Any]) -> Dict[str, Any]:
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
        inst["enchant_level"] = int(level)
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
    path = Path(DEFAULT_INSTANCES_PATH)
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
    global _CACHE
    _CACHE = None
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
    global _CACHE
    _CACHE = None
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
    raw = _load_instances_raw()
    cat = _catalog()
    out: List[str] = []
    tgt = (int(year), int(x), int(y))
    for inst in raw:
        pos = _pos_of(inst)
        if pos and pos == tgt:
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
    raw = _load_instances_raw()
    out: List[str] = []
    tgt = (int(year), int(x), int(y))
    for inst in raw:
        pos = _pos_of(inst)
        if pos and pos == tgt:
            item_id = (
                inst.get("item_id")
                or inst.get("catalog_id")
                or inst.get("id")
            )
            if item_id:
                out.append(str(item_id))
    return out

# ---------------------------------------------------------------------------
# Extra helpers for ground/inventory transfers

_CACHE: Optional[List[Dict[str, Any]]] = None

def _cache() -> List[Dict[str, Any]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_instances_raw()
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
    global _CACHE
    _CACHE = None
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
    raw = _cache()
    for inst in raw:
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            return inst
    return None

def clear_position(iid: str) -> None:
    raw = _cache()
    for inst in raw:
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            inst.pop("pos", None)
            inst.pop("year", None)
            inst.pop("x", None)
            inst.pop("y", None)
            break

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
    }
    cat = items_catalog.load_catalog()
    tpl = cat.get(str(item_id)) if cat else None
    if tpl and int(tpl.get("charges_max", 0) or 0) > 0:
        inst["charges"] = int(tpl.get("charges_max"))
    raw.append(inst)
    _save_instances_raw(raw)
    return iid

