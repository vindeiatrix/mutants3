from __future__ import annotations
import json, os, tempfile, uuid
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any

DEFAULT_INSTANCES_PATH = "state/items/instances.json"
FALLBACK_INSTANCES_PATH = "state/instances.json"  # auto-fallback if the new path isn't used yet

def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
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
        """Create a new instance from a base catalog item."""
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
        if self._dirty:
            _atomic_write_json(self._path, self._items)
            self._dirty = False

def load_instances(path: str = DEFAULT_INSTANCES_PATH) -> ItemsInstances:
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
