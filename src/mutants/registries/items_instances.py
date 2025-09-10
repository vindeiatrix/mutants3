from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any
import uuid

DEFAULT_INSTANCES_PATH = "state/items/instances.json"

def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(prefix=path.name, dir=str(path.parent))[1])
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

class ItemsInstances:
    def __init__(self, path: str, items: List[Dict[str, Any]]):
        self._path = Path(path)
        self._items: List[Dict[str, Any]] = items
        self._by_id: Dict[str, Dict[str, Any]] = {it["instance_id"]: it for it in items}
        self._dirty = False

    def get(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(instance_id)

    def list_for_item(self, item_id: str) -> Iterable[Dict[str, Any]]:
        return (it for it in self._items if it.get("item_id") == item_id)

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
        inst = {
            "instance_id": instance_id,
            "item_id": base_item["item_id"],
            "enchanted": "no",
            "wear": 0,
        }
        charges_start = int(base_item.get("charges_start", 0) or 0)
        if charges_start > 0:
            inst["charges"] = charges_start
        # skull provenance fields added by loot systems later as needed:
        # inst["skull_monster_type_id"] = "..."; inst["skull_monster_name"] = "..."
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

    def save(self) -> None:
        if not self._dirty:
            return
        _atomic_write_json(self._path, self._items)
        self._dirty = False

def load_instances(path: str = DEFAULT_INSTANCES_PATH) -> ItemsInstances:
    p = Path(path)
    if not p.exists():
        # Keep it minimal: empty list when absent.
        return ItemsInstances(path, [])
    with p.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []
    # Support either [] or {"instances": []}
    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return ItemsInstances(path, items)
