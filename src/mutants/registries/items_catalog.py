"""Normalized view over the static items catalog.

This module is the authoritative reader for ``state/items/catalog.json``.  It performs
schema migrations, enforces invariants, and exposes an ``ItemsCatalog`` wrapper with
lookup helpers used by services and commands.

Examples
--------
>>> from mutants.registries import items_catalog
>>> catalog = items_catalog.load_catalog()
>>> sword = catalog.require("short_sword")
>>> sword["spawnable"]
True
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mutants.state import state_path

from .sqlite_store import SQLiteConnectionManager

DEFAULT_CATALOG_PATH = state_path("items", "catalog.json")
FALLBACK_CATALOG_PATH = DEFAULT_CATALOG_PATH

DISALLOWED_ENCHANTABLE_FIELDS: Tuple[Tuple[str, str], ...] = (
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
    """In-memory view of the validated items catalog."""

    def __init__(self, items: List[Dict[str, Any]]):
        """Create a catalog wrapper.

        Parameters
        ----------
        items
            Normalised item dictionaries returned by :func:`load_catalog`.
        """

        self._items_list = items
        self._by_id: Dict[str, Dict[str, Any]] = {it["item_id"]: it for it in items}

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Return the catalog entry for ``item_id`` or ``None`` when missing."""

        return self._by_id.get(item_id)

    def require(self, item_id: str) -> Dict[str, Any]:
        """Return the catalog entry for ``item_id`` or raise ``KeyError``."""

        it = self.get(item_id)
        if not it:
            raise KeyError(f"Unknown item_id: {item_id}")
        return it

    def list_spawnable(self) -> List[Dict[str, Any]]:
        """Return a list of entries explicitly marked ``spawnable: true``."""

        return [it for it in self._items_list if it.get("spawnable") is True]

def _coerce_legacy_bools(items: List[Dict[str, Any]]) -> None:
    """Convert legacy ``"yes"``/``"no"`` strings to booleans in-place."""
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
    """Alias legacy fields, infer defaults, and validate items in-place.

    Parameters
    ----------
    items
        Mutable item dictionaries that will be normalised.

    Returns
    -------
    tuple[list[str], list[str]]
        A ``(warnings, errors)`` tuple collected during normalisation.
    """
    warnings: List[str] = []
    errors: List[str] = []
    for it in items:
        iid = it.get("item_id", "<unknown>")

        def _coerce_non_negative_int(field: str, raw: Any) -> Optional[int]:
            if raw is None:
                return None
            try:
                value = int(raw)
            except (TypeError, ValueError):
                errors.append(f"{iid}: {field} must be an integer >= 0.")
                return None
            if value < 0:
                errors.append(f"{iid}: {field} must be an integer >= 0.")
                return None
            return value

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
            if enchantable is None:
                it["enchantable"] = False
                enchantable = False
            else:
                errors.append(f"{iid}: enchantable must be explicitly true or false.")

        if isinstance(enchantable, bool):
            for field_name, flag_name in DISALLOWED_ENCHANTABLE_FIELDS:
                if bool(it.get(field_name)) and enchantable:
                    errors.append(
                        f"{iid}: {flag_name} items must declare enchantable: false."
                    )

        if "spawnable" in it:
            if not isinstance(it.get("spawnable"), bool):
                errors.append(f"{iid}: spawnable must be explicitly true or false.")
        else:
            errors.append(f"{iid}: spawnable must be explicitly true or false.")

        is_ranged = bool(it.get("ranged"))

        legacy_power = it.get("base_power")
        melee_power = it.get("base_power_melee")
        bolt_power = it.get("base_power_bolt")

        if legacy_power is not None:
            errors.append(
                f"{iid}: base_power is no longer allowed; "
                "run scripts/expand_item_power_fields.py to migrate."
            )

        melee_value = _coerce_non_negative_int("base_power_melee", melee_power)
        if melee_value is not None:
            it["base_power_melee"] = melee_value
        elif "base_power_melee" in it:
            it.pop("base_power_melee", None)

        bolt_value = _coerce_non_negative_int("base_power_bolt", bolt_power)
        if bolt_value is not None:
            it["base_power_bolt"] = bolt_value
        elif "base_power_bolt" in it:
            it.pop("base_power_bolt", None)

        if is_ranged and it.get("spawnable") is True:
            warnings.append(
                f"{iid}: ranged items marked spawnable; ensure this is intentional."
            )

        if is_ranged:
            if "base_power_melee" not in it or "base_power_bolt" not in it:
                errors.append(
                    f"{iid}: ranged items must define base_power_melee and base_power_bolt."
                )

        legacy_poison_flag = it.get("poisonous")
        legacy_poison_power = it.get("poison_power")
        poison_melee = it.get("poison_melee")
        poison_bolt = it.get("poison_bolt")

        if poison_melee is None and poison_bolt is None and legacy_poison_flag is not None:
            flag = bool(legacy_poison_flag)
            it["poison_melee"] = flag
            it["poison_bolt"] = flag
            if legacy_poison_power is not None:
                power_value = _coerce_non_negative_int("poison_power", legacy_poison_power)
                if power_value is not None:
                    it["poison_melee_power"] = power_value
                    it["poison_bolt_power"] = power_value
            else:
                it["poison_melee_power"] = 0
                it["poison_bolt_power"] = 0

        if not isinstance(it.get("poison_melee"), bool):
            it["poison_melee"] = bool(it.get("poison_melee"))
        if not isinstance(it.get("poison_bolt"), bool):
            it["poison_bolt"] = bool(it.get("poison_bolt"))

        if legacy_poison_flag is not None or legacy_poison_power is not None:
            warnings.append(
                f"{iid}: poisonous/poison_power will become errors after 2024-09-01; "
                "run scripts/expand_item_power_fields.py to migrate."
            )

        melee_poison_power = _coerce_non_negative_int(
            "poison_melee_power", it.get("poison_melee_power")
        )
        if melee_poison_power is not None:
            it["poison_melee_power"] = melee_poison_power
        elif "poison_melee_power" in it:
            it.pop("poison_melee_power", None)

        bolt_poison_power = _coerce_non_negative_int(
            "poison_bolt_power", it.get("poison_bolt_power")
        )
        if bolt_poison_power is not None:
            it["poison_bolt_power"] = bolt_poison_power
        elif "poison_bolt_power" in it:
            it.pop("poison_bolt_power", None)

        if it.get("poison_melee") and "poison_melee_power" not in it:
            it["poison_melee_power"] = 0
        if it.get("poison_bolt") and "poison_bolt_power" not in it:
            it["poison_bolt_power"] = 0

    return warnings, errors

def _load_items_from_store(manager: SQLiteConnectionManager) -> List[Dict[str, Any]]:
    conn = manager.connect()
    cur = conn.execute(
        "SELECT item_id, data_json FROM items_catalog ORDER BY item_id ASC"
    )
    rows = cur.fetchall()
    if not rows:
        raise FileNotFoundError(
            f"Missing catalog entries in SQLite store at {manager.path}"
        )

    items: List[Dict[str, Any]] = []
    for row in rows:
        raw = row["data_json"]
        if not isinstance(raw, str):
            raise ValueError(f"items_catalog row {row['item_id']} missing JSON payload")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(
                "items_catalog rows must decode to JSON objects (dicts)"
            )
        data.setdefault("item_id", row["item_id"])
        items.append(data)
    return items


def load_catalog(path: Path | str | None = None) -> ItemsCatalog:
    """Load the items catalog from the SQLite store.

    Parameters
    ----------
    path
        Optional path to the SQLite database file.  When omitted the default
        state database configured for the runtime is used.

    Returns
    -------
    ItemsCatalog
        Wrapper providing lookup helpers.

    Raises
    ------
    FileNotFoundError
        If the catalog table is empty.
    ValueError
        If any catalog entry violates invariants (missing flags, invalid ranges, etc.).
    """

    manager = SQLiteConnectionManager(path) if path is not None else SQLiteConnectionManager()
    items = _load_items_from_store(manager)
    _coerce_legacy_bools(items)
    warnings, errors = _normalize_items(items)
    for msg in warnings:
        LOG.warning(msg)
    if errors:
        for msg in errors:
            LOG.error(msg)
        raise ValueError("invalid catalog items")
    return ItemsCatalog(items)


def catalog_defaults(item_id: str) -> Dict[str, Any]:
    """Return runtime defaults inferred from the catalog for ``item_id``."""

    defaults: Dict[str, Any] = {}
    if not item_id:
        return defaults

    try:
        catalog = load_catalog()
    except FileNotFoundError:
        return defaults

    template = catalog.get(str(item_id)) if catalog else None
    if not isinstance(template, dict):
        return defaults

    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, str):
            lv = value.strip().lower()
            if lv in {"yes", "true", "1"}:
                return True
            if lv in {"no", "false", "0"}:
                return False
        return bool(value)

    defaults["condition"] = 100
    defaults["enchant_level"] = 0
    defaults["enchant"] = 0

    if "god_tier" in template:
        defaults["god_tier"] = _coerce_bool(template.get("god_tier"))

    try:
        charges_max = int(template.get("charges_max", 0) or 0)
    except (TypeError, ValueError):
        charges_max = 0
    uses_charges = template.get("uses_charges")
    if charges_max > 0 and (uses_charges is None or bool(uses_charges)):
        defaults["charges"] = charges_max

    return defaults


def max_charges(item_id: str | None) -> int:
    """Return the maximum number of charges available for ``item_id``."""

    if not item_id:
        return 0

    try:
        catalog = load_catalog()
    except FileNotFoundError:
        return 0

    template = catalog.get(str(item_id)) if catalog else None
    if not isinstance(template, dict):
        return 0

    if template.get("uses_charges") is False:
        return 0

    try:
        return int(template.get("charges_max", 0) or 0)
    except (TypeError, ValueError):
        return 0
