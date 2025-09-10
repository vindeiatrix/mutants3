from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any

DEFAULT_CATALOG_PATH = "state/items/catalog.json"

class ItemsCatalog:
    def __init__(self, items: List[Dict[str, Any]]):
        self._items_list = items
        self._by_id: Dict[str, Dict[str, Any]] = {it["item_id"]: it for it in items}

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(item_id)

    def require(self, item_id: str) -> Dict[str, Any]:
        it = self.get(item_id)
        if not it:
            raise KeyError(f"Unknown item_id: {item_id}")
        return it

    def list_spawnable(self) -> List[Dict[str, Any]]:
        return [it for it in self._items_list if it.get("spawnable", "no") == "yes"]

def load_catalog(path: str = DEFAULT_CATALOG_PATH) -> ItemsCatalog:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing catalog at {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError('catalog.json must be a list of items or {"items": [...]}')

    return ItemsCatalog(items)
