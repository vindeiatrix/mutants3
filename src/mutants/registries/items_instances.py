from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any

from mutants.io.atomic import atomic_write_json

DEFAULT_INSTANCES_PATH = "state/items/instances.json"
FALLBACK_INSTANCES_PATH = "state/instances.json"  # auto-fallback if the new path isn't used yet

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
        Seeds charges if base has charges_start; sets enchanted=no, wear=0 by default.
        """
        instance_id = f"{base_item['item_id']}#{uuid.uuid4().hex[:8]}"
        inst: Dict[str, Any] = {
            "instance_id": instance_id,
            "item_id": base_item["item_id"],
            "enchanted": "no",
            "wear": 0,
        }
        charges_start = int(base_item.get("charges_start", 0) or 0)
        if charges_start > 0:
            inst["charges"] = charges_start
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
