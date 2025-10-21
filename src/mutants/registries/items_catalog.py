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
import random
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Alias for :meth:`get` used by higher-level services."""

        return self.get(item_id)

    def require(self, item_id: str) -> Dict[str, Any]:
        """Return the catalog entry for ``item_id`` or raise ``KeyError``."""

        it = self.get(item_id)
        if not it:
            raise KeyError(f"Unknown item_id: {item_id}")
        return it

    def list_spawnable(self) -> List[Dict[str, Any]]:
        """Return a list of entries explicitly marked ``spawnable: true``."""

        return [it for it in self._items_list if it.get("spawnable") is True]


def instance_defaults(item_id: str) -> Dict[str, Any]:
    """Dynamic defaults for a freshly minted instance."""

    try:
        catalog = load_catalog()
    except FileNotFoundError:
        c: Dict[str, Any] = {}
    else:
        entry = catalog.get(str(item_id)) if catalog else None
        c = entry if isinstance(entry, dict) else {}

    defaults: Dict[str, Any] = {"condition": 100, "enchant": 0}

    ranged_meta = c.get("ranged") or {}
    charges_source: Any
    if isinstance(ranged_meta, dict) and "charges_max" in ranged_meta:
        charges_source = ranged_meta.get("charges_max")
    else:
        charges_source = c.get("charges_max")

    try:
        cm = int(charges_source) if charges_source is not None else None
    except (TypeError, ValueError):
        cm = None

    if cm is not None and cm >= 0:
        defaults["charges"] = cm

    return defaults

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


def list_spawnable_items() -> List[Dict[str, Any]]:
    """Return spawnable catalog entries with weights and caps."""

    manager = SQLiteConnectionManager()
    from mutants.bootstrap import daily_litter as dl  # local import to avoid cycle

    try:
        spawnables = dl._load_spawnables_from_db(manager)
        results: List[Dict[str, Any]] = []
        for item_id, cfg in spawnables.items():
            entry = dict(cfg)
            entry["item_id"] = item_id
            results.append(entry)
        return results
    finally:
        manager.close()


def _spawn_rules() -> Dict[str, Any]:
    from mutants.bootstrap import daily_litter as dl  # local import

    rules_path = state_path("items", "spawn_rules.json")
    return dl._load_spawn_rules(rules_path)


def daily_target_per_year() -> int:
    rules = _spawn_rules()
    try:
        return int(rules.get("daily_target_per_year"))
    except (TypeError, ValueError):
        from mutants.bootstrap import daily_litter as dl  # local import

        return dl.DAILY_TARGET_DEFAULT


def _max_ground_per_tile() -> int:
    rules = _spawn_rules()
    try:
        return int(rules.get("max_ground_per_tile"))
    except (TypeError, ValueError):
        from mutants.bootstrap import daily_litter as dl  # local import

        return dl.MAX_PER_TILE_DEFAULT


def playable_years() -> List[int]:
    from mutants.bootstrap import daily_litter as dl  # local import

    world_dir = state_path("world")
    return dl._list_years(world_dir)


_CATALOG_CACHE: ItemsCatalog | None = None


def get() -> ItemsCatalog:
    """Return a cached :class:`ItemsCatalog` instance."""

    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = load_catalog()
    return _CATALOG_CACHE


def _spawnable_map(spawnables: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[int]]]:
    mapping: Dict[str, Dict[str, Optional[int]]] = {}
    for entry in spawnables:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        if not item_id:
            continue
        weight_raw = entry.get("weight")
        try:
            weight = int(weight_raw)
        except (TypeError, ValueError):
            weight = 0
        if weight <= 0:
            continue
        cfg: Dict[str, Optional[int]] = {"weight": weight}
        cap_raw = entry.get("cap_per_year")
        if cap_raw is not None:
            try:
                cfg["cap_per_year"] = int(cap_raw)
            except (TypeError, ValueError):
                cfg["cap_per_year"] = None
        mapping[str(item_id)] = cfg
    return mapping


def generate_daily_litter_for_year(
    year: int,
    daily_target: int,
    spawnables: Sequence[Dict[str, Any]],
    *,
    origin: Optional[str] = None,
) -> Iterable[Dict[str, Any]]:
    from mutants.bootstrap import daily_litter as dl  # local import

    if daily_target <= 0:
        return []

    tiles = dl._collect_open_tiles_for_year(year, state_path("world"))
    if not tiles:
        return []

    spawn_map = _spawnable_map(spawnables)
    if not spawn_map:
        return []

    manager = SQLiteConnectionManager()
    conn = manager.connect()
    try:
        per_tile_all = dl._fetch_per_tile_counts(conn)
        per_year_all = dl._fetch_per_year_item_counts(conn)

        per_tile = dict(per_tile_all)
        per_year = {yr: dict(counts) for yr, counts in per_year_all.items()}

        pool = dl._build_weighted_pool(year, spawn_map, per_year)
        items, cumulative, total_weight = dl._prepare_weight_tables(pool)
        if not items or total_weight <= 0:
            return []

        max_per_tile = _max_ground_per_tile()
        if max_per_tile <= 0:
            max_per_tile = dl.MAX_PER_TILE_DEFAULT

        created_base = int(time() * 1000)
        seq = 0
        results: List[Dict[str, Any]] = []
        attempts = 0
        max_attempts = daily_target * 20

        while len(results) < daily_target and attempts < max_attempts:
            attempts += 1
            if not items or total_weight <= 0:
                break
            r = random.randint(1, total_weight)
            lo, hi = 0, len(cumulative) - 1
            pick = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if r <= cumulative[mid]:
                    pick = mid
                    hi = mid - 1
                else:
                    lo = mid + 1

            item_id = items[pick]
            cap = spawn_map[item_id].get("cap_per_year")
            already = per_year.get(year, {}).get(item_id, 0)
            if cap is not None and already >= cap:
                pool = dl._build_weighted_pool(year, spawn_map, per_year)
                items, cumulative, total_weight = dl._prepare_weight_tables(pool)
                if not items or total_weight <= 0:
                    break
                continue

            x, y = tiles[random.randrange(0, len(tiles))]
            key = dl._tile_key(year, x, y)
            if per_tile.get(key, 0) >= max_per_tile:
                continue

            created_at = created_base + seq
            seq += 1
            record = dl._create_spawn_record(item_id, year, x, y, created_at)
            if origin is not None:
                record[dl.ORIGIN_FIELD] = str(origin)
            results.append(record)

            per_tile[key] = per_tile.get(key, 0) + 1
            per_year.setdefault(year, {})
            per_year[year][item_id] = already + 1

        return results
    finally:
        manager.close()


def breakdown_summary(records: Iterable[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for record in records:
        item_id = record.get("item_id")
        if not item_id:
            continue
        key = str(item_id)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    parts = [f"{item_id}\u00d7{counts[item_id]}" for item_id in sorted(counts)]
    return ", ".join(parts)


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
