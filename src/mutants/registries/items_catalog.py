from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

DEFAULT_CATALOG_PATH = "state/items/catalog.json"
FALLBACK_CATALOG_PATH = "state/catalog.json"  # auto-fallback if the new path isn't used yet

DISALLOWED_ENCHANTABLE_FIELDS = (
    ("ranged", "ranged"),
    ("spawnable", "spawnable"),
    ("potion", "potion"),
    ("is_potion", "potion"),
    ("spell_component", "spell_component"),
    ("spell_components", "spell_component"),
    ("is_spell_component", "spell_component"),
    ("key", "key"),
    ("is_key", "key"),
    ("skull", "skull"),
    ("is_skull", "skull"),
)

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
        return [it for it in self._items_list if it.get("spawnable") is True]

def _read_items_from_file(p: Path) -> List[Dict[str, Any]]:
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError('catalog.json must be a list of items or {"items": [...]}')


def _coerce_legacy_bools(items: List[Dict[str, Any]]) -> None:
    """Convert legacy "yes"/"no" string fields to booleans in-place."""
    for it in items:
        for k, v in list(it.items()):
            if isinstance(v, str):
                lv = v.lower()
                if lv == "yes":
                    it[k] = True
                elif lv == "no":
                    it[k] = False


LOG = logging.getLogger(__name__)


def _normalize_items(items: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    """Alias legacy fields, infer defaults, and validate items in-place."""
    warnings: List[str] = []
    errors: List[str] = []
    for it in items:
        iid = it.get("item_id", "<unknown>")

        if "charges_max" not in it and "charges_start" in it:
            it["charges_max"] = it["charges_start"]
        if "charges_start" in it:
            it.pop("charges_start", None)

        charges_max = int(it.get("charges_max", 0) or 0)
        if "uses_charges" not in it:
            it["uses_charges"] = charges_max > 0
        uses_charges = bool(it.get("uses_charges"))
        if uses_charges and charges_max <= 0:
            errors.append(f"{iid}: uses_charges true requires charges_max > 0.")
        if not uses_charges and charges_max > 0:
            warnings.append(
                f"{iid}: charges_max present but uses_charges false -> flipping to true."
            )
            it["uses_charges"] = True
        if not it.get("uses_charges"):
            it.pop("charges_max", None)

        enchantable = it.get("enchantable")
        if not isinstance(enchantable, bool):
            errors.append(f"{iid}: enchantable must be explicitly true or false.")

        if isinstance(enchantable, bool):
            for field_name, flag_name in DISALLOWED_ENCHANTABLE_FIELDS:
                if bool(it.get(field_name)) and enchantable:
                    errors.append(
                        f"{iid}: {flag_name} items must declare enchantable: false."
                    )

    return warnings, errors

def load_catalog(path: str = DEFAULT_CATALOG_PATH) -> ItemsCatalog:
    primary = Path(path)
    fallback = Path(FALLBACK_CATALOG_PATH)
    if primary.exists():
        items = _read_items_from_file(primary)
    elif fallback.exists():
        items = _read_items_from_file(fallback)
    else:
        raise FileNotFoundError(f"Missing catalog: tried {primary} then {fallback}")
    _coerce_legacy_bools(items)
    warnings, errors = _normalize_items(items)
    for msg in warnings:
        LOG.warning(msg)
    if errors:
        for msg in errors:
            LOG.error(msg)
        raise ValueError("invalid catalog items")
    return ItemsCatalog(items)
