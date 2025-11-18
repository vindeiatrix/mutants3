from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import MutableSet
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

# NOTE: Imported by ``mutants.registries.json_store`` via :func:`get_stores`.

from mutants.state import state_path
from .storage import get_stores
from . import items_catalog
from .items_catalog import instance_defaults

DEFAULT_INSTANCES_PATH = state_path("items", "instances.json")
FALLBACK_INSTANCES_PATH = state_path("instances.json")  # auto-fallback if the new path isn't used yet
CATALOG_PATH = state_path("items", "catalog.json")

LOG = logging.getLogger("mutants.itemsdbg")


class _RemoveSentinel:
    pass


REMOVE_FIELD = _RemoveSentinel()


def _strict_duplicate_default() -> bool:
    env = os.getenv("MUTANTS_STRICT_IIDS")
    if env is not None:
        return env.strip() == "1"
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or os.getenv("WORLD_DEBUG") == "1"


STRICT_DUP_IIDS = _strict_duplicate_default()

BROKEN_WEAPON_ID = "broken_weapon"
BROKEN_ARMOUR_ID = "broken_armour"
_BROKEN_ITEM_IDS = {BROKEN_WEAPON_ID, BROKEN_ARMOUR_ID}

NOT_ENCHANTABLE_REASONS = (
    "not_enchantable",
    "condition",
    "broken",
    "max_enchant",
)


def mint_iid(*, seen: Optional[MutableSet[str] | Iterable[str]] = None) -> str:
    """Return a fresh unique item instance identifier.

    Parameters
    ----------
    seen
        Optional collection used to seed the set of IDs that must not be reused. The
        collection is updated in-place when it is a mutable set.

    Returns
    -------
    str
        Hex string suitable for storing in ``iid`` / ``instance_id`` fields.
    """

    seen_ids: set[str]
    updater: Optional[MutableSet[str]]
    if seen is None:
        seen_ids = set()
        updater = None
    elif isinstance(seen, MutableSet):
        seen_ids = {str(token) for token in seen}
        updater = seen
    else:
        seen_ids = {str(token) for token in seen}
        updater = None

    while True:
        candidate = uuid.uuid4().hex
        if candidate not in seen_ids:
            seen_ids.add(candidate)
            if updater is not None:
                updater.add(candidate)
            return candidate


def remint_iid(inst: MutableMapping[str, Any], *, seen: Optional[Iterable[str]] = None) -> str:
    """Assign a new ``iid`` / ``instance_id`` to ``inst`` and return it.

    Parameters
    ----------
    inst
        Mutable instance payload to update in-place.
    seen
        Optional iterable of identifiers that must not be reused.

    Returns
    -------
    str
        The new identifier written to ``inst``.
    """

    existing = set(str(token) for token in seen or [])
    while True:
        candidate = mint_iid(seen=existing)
        if candidate not in existing:
            existing.add(candidate)
            inst["iid"] = candidate
            inst["instance_id"] = candidate
            return candidate


def _instance_id(inst: Dict[str, Any]) -> str:
    value = inst.get("iid") or inst.get("instance_id")
    return str(value) if value is not None else ""


def _item_id(inst: Dict[str, Any]) -> str:
    value = inst.get("item_id") or inst.get("catalog_id") or inst.get("id")
    return str(value) if value is not None else ""


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        lv = value.strip().lower()
        if lv in {"yes", "true", "1"}:
            return True
        if lv in {"no", "false", "0"}:
            return False
    return bool(value)


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

    god_tier_flag = _coerce_bool(inst.get("god_tier")) if "god_tier" in inst else False
    if inst.get("god_tier") != god_tier_flag or "god_tier" not in inst:
        inst["god_tier"] = god_tier_flag
        changed = True

    return changed


def _normalize_instances(instances: Iterable[Dict[str, Any]]) -> bool:
    changed = False
    for inst in instances:
        if _normalize_instance(inst):
            changed = True
    return changed


def is_ground_full(year: int, x: int, y: int) -> bool:
    """Return ``True`` when the ground at ``(year, x, y)`` is at capacity."""

    from mutants.services.item_transfer import GROUND_CAP

    ground = list_instances_at(year, x, y)
    return len(ground) >= GROUND_CAP


def _detect_duplicate_iids(instances: Iterable[Dict[str, Any]]) -> List[str]:
    seen: Dict[str, int] = {}
    duplicates: List[str] = []
    for inst in instances:
        iid = _instance_id(inst)
        if not iid:
            continue
        if iid in seen:
            duplicates.append(iid)
        else:
            seen[iid] = 1
    return duplicates


def _handle_duplicates(
    duplicates: List[str], *, strict: Optional[bool] = None, path: Optional[Path] = None
) -> None:
    if not duplicates:
        return

    strict_mode = STRICT_DUP_IIDS if strict is None else bool(strict)
    target = path.resolve() if path else None
    message = (
        "[itemsdbg] DUPLICATE_IIDS_DETECTED count=%s sample=%s path=%s",
        len(duplicates),
        duplicates[:5],
        target,
    )
    if strict_mode:
        LOG.error(*message)
        raise ValueError(
            "duplicate item instance ids detected; run tools.fix_iids to repair"
        )
    LOG.info(*message)

def enchant_blockers_for(
    iid: str, *, template: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Return legacy enchantment blockers for ``iid``.

    Parameters
    ----------
    iid
        Instance identifier to inspect.
    template
        Ignored legacy parameter retained for compatibility.

    Returns
    -------
    list[str]
        ``["missing_instance"]`` when the IID cannot be resolved, otherwise an empty
        list.
    """

    inst = get_instance(iid)
    if not inst:
        return ["missing_instance"]

    return []


def is_enchantable(iid: str, *, template: Optional[Dict[str, Any]] = None) -> bool:
    """Return ``True`` when the instance exists.

    Parameters
    ----------
    iid
        Instance identifier to inspect.
    template
        Ignored legacy parameter retained for compatibility.

    Returns
    -------
    bool
        ``True`` if the instance exists. Catalogue invariants govern enchantment policy.
    """

    return get_instance(iid) is not None



def load_instances(
    path: Path | str = DEFAULT_INSTANCES_PATH, *, strict: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """Load and normalise instances from the configured backend."""

    resolved = Path(path)
    default_path = Path(DEFAULT_INSTANCES_PATH)
    fallback_path = Path(FALLBACK_INSTANCES_PATH)

    if resolved not in {default_path, fallback_path}:
        return _load_instances_from_path(resolved, strict=strict)

    return _load_instances_raw(strict=strict)


# ---------------------------------------------------------------------------
# lightweight read helpers --------------------------------------------------


def _load_instances_from_path(
    path: Path, *, strict: Optional[bool] = None
) -> List[Dict[str, Any]]:
    import json

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return []
    except (PermissionError, IsADirectoryError, json.JSONDecodeError):
        LOG.error("Failed to load instances from %s", path, exc_info=True)
        raise

    if isinstance(data, dict) and "instances" in data:
        items = data["instances"]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    if not isinstance(items, list):
        return []

    duplicates = _detect_duplicate_iids(items)
    _handle_duplicates(duplicates, strict=strict, path=path)

    _normalize_instances(items)
    return list(items)


def _load_instances_raw(*, strict: Optional[bool] = None) -> List[Dict[str, Any]]:
    store = _items_store()
    items = [_inflate_store_record(inst) for inst in store.snapshot()]

    duplicates = _detect_duplicate_iids(items)
    _handle_duplicates(duplicates, strict=strict)

    return items


def _save_instances_raw(instances: List[Dict[str, Any]]) -> None:
    raise RuntimeError("items_instances: snapshot/replace_all is forbidden on SQLite")


def _index_of(instances: List[Dict[str, Any]], iid: str) -> int:
    for idx, inst in enumerate(instances):
        inst_id = inst.get("iid") or inst.get("instance_id")
        if inst_id and str(inst_id) == str(iid):
            return idx
    raise KeyError(iid)


def charges_max_for(iid: str) -> int:
    """Return the charge capacity for ``iid`` considering overrides."""
    inst = get_instance(iid) or {}
    tpl_id = inst.get("item_id")
    tpl = items_catalog.load_catalog().get(str(tpl_id)) if tpl_id else {}
    return int(inst.get("charges_max_override") or (tpl.get("charges_max") if tpl else 0) or 0)


def spend_charge(iid: str) -> bool:
    """Decrement charge by one when available and return ``True`` on success."""
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


def recharge_full(iid: str) -> None:
    """Recharge ``iid`` to full using targeted updates."""

    inst = _items_store().get_by_iid(str(iid))
    if not inst:
        raise KeyError(iid)

    max_ch = items_catalog.max_charges(inst.get("item_id"))
    if max_ch > 0:
        _items_store().update_fields(str(iid), charges=max_ch)

def _pos_of(inst: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    if isinstance(inst.get("pos"), dict):
        p = inst["pos"]
        try:
            return int(p["year"]), int(p["x"]), int(p["y"])
        except (KeyError, TypeError, ValueError):
            LOG.error("Invalid nested position in instance: %r", inst, exc_info=True)
            raise
    if all(k in inst for k in ("year", "x", "y")):
        try:
            return int(inst["year"]), int(inst["x"]), int(inst["y"])
        except (KeyError, TypeError, ValueError):
            LOG.error("Invalid position in instance: %r", inst, exc_info=True)
            raise
    return None


def _catalog() -> Dict[str, Any]:
    import json

    path = Path(CATALOG_PATH)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (PermissionError, IsADirectoryError, json.JSONDecodeError):
        LOG.error("Failed to load catalog from %s", path, exc_info=True)
        raise
    return data.get("items", data) if isinstance(data, dict) else {}


def _display_name(item_id: str, cat: Dict[str, Any]) -> str:
    meta = cat.get(item_id)
    if isinstance(meta, dict):
        for key in ("name", "display_name", "title"):
            if isinstance(meta.get(key), str):
                return meta[key]
    return item_id


def list_at(year: int, x: int, y: int) -> List[str]:
    """Return display labels for items at the requested location."""
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
        # Only items with no owner are on the ground.
        if inst.get("owner") not in (None, "", 0):
            continue
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


def invalidate_cache() -> None:
    """Legacy no-op retained for API compatibility."""
    return None


def _items_store():
    return get_stores().items


def mint_on_ground_with_defaults(
    item_id: str,
    *,
    year: int,
    x: int,
    y: int,
    origin: str = "debug_add",
    overrides: dict | None = None,
) -> str:
    """Mint an item directly onto the ground with catalog defaults applied."""

    store = _items_store()
    iid = mint_iid()
    record: Dict[str, Any] = {
        "iid": iid,
        "item_id": str(item_id),
        "year": int(year),
        "x": int(x),
        "y": int(y),
        "owner": None,
        "origin": origin,
        "created_at": int(time.time() * 1000),
    }
    record.update(instance_defaults(item_id))
    if overrides:
        record.update(overrides)
    store.mint(record)
    return iid


def _apply_catalog_defaults(target: MutableMapping[str, Any]) -> None:
    """Merge catalog-derived defaults into ``target`` when available."""

    item_id = target.get("item_id")
    if not item_id:
        return

    try:
        defaults = items_catalog.catalog_defaults(str(item_id))
    except FileNotFoundError:
        return

    for key, value in defaults.items():
        target.setdefault(key, value)


def _inflate_store_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    inst: Dict[str, Any] = dict(record)

    iid = inst.get("iid")
    inst["iid"] = str(iid) if iid is not None else ""
    inst["instance_id"] = inst["iid"]

    item_id = inst.get("item_id")
    inst["item_id"] = str(item_id) if item_id is not None else ""

    try:
        year = int(inst.get("year", -1))
    except (TypeError, ValueError):
        year = -1
    try:
        x = int(inst.get("x", -1))
    except (TypeError, ValueError):
        x = -1
    try:
        y = int(inst.get("y", -1))
    except (TypeError, ValueError):
        y = -1

    inst["year"] = year
    inst["x"] = x
    inst["y"] = y
    inst["pos"] = {"year": year, "x": x, "y": y}

    enchant_source = inst.get("enchant_level", inst.get("enchant"))
    inst["enchant_level"] = _sanitize_enchant_level(enchant_source)
    inst["enchant"] = inst["enchant_level"]

    condition_source = inst.get("condition")
    inst["condition"] = _sanitize_condition(condition_source)

    owner = inst.get("owner")
    if owner is not None:
        inst["owner"] = str(owner)
        inst["owner_iid"] = inst["owner"]
    else:
        inst.setdefault("owner_iid", None)

    origin = inst.get("origin")
    if origin is not None:
        inst["origin"] = str(origin)

    drop_source = inst.get("drop_source")
    if drop_source is not None:
        inst["drop_source"] = str(drop_source)

    _apply_catalog_defaults(inst)
    _normalize_instance(inst)
    inst["enchant"] = inst["enchant_level"]
    return inst


def _store_payload_from_instance(inst: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        year = int(inst.get("year", -1))
    except (TypeError, ValueError):
        year = -1
    try:
        x = int(inst.get("x", -1))
    except (TypeError, ValueError):
        x = -1
    try:
        y = int(inst.get("y", -1))
    except (TypeError, ValueError):
        y = -1

    owner_value = inst.get("owner")
    if isinstance(owner_value, Mapping):
        try:
            owner_value = json.dumps(owner_value, sort_keys=True)
        except Exception:
            owner_value = str(owner_value)

    payload: Dict[str, Any] = {
        "iid": str(inst.get("iid")),
        "item_id": str(inst.get("item_id")),
        "year": year,
        "x": x,
        "y": y,
        "owner": owner_value,
        "enchant": _sanitize_enchant_level(inst.get("enchant_level")),
        "condition": _sanitize_condition(inst.get("condition")),
        "origin": inst.get("origin"),
        "drop_source": inst.get("drop_source"),
        "created_at": inst.get("created_at"),
    }
    charges_value = inst.get("charges")
    if charges_value is not None:
        try:
            payload["charges"] = int(charges_value)
        except (TypeError, ValueError):
            pass
    _apply_catalog_defaults(payload)
    return payload


def _cache() -> List[Dict[str, Any]]:
    """Return a fresh snapshot of instances."""

    return list(_load_instances_raw())


def mint_instance(item_id: str, origin: str = "unknown") -> str:
    """Create, persist, and return a new instance for ``item_id``."""

    store = _items_store()

    inst: Dict[str, Any] = {
        "iid": "",
        "instance_id": "",
        "item_id": str(item_id),
        "origin": str(origin),
        "enchanted": "no",
        "year": -1,
        "x": -1,
        "y": -1,
    }

    _apply_catalog_defaults(inst)
    inst.setdefault("enchant_level", 0)
    inst.setdefault("condition", 100)
    inst.setdefault("god_tier", False)

    while True:
        iid = mint_iid()
        inst["iid"] = iid
        inst["instance_id"] = iid
        _normalize_instance(inst)
        try:
            store.mint(_store_payload_from_instance(inst))
            return iid
        except KeyError:
            continue


def mint_item(
    *,
    item_id: str,
    pos: Sequence[int] | Mapping[str, Any] | None,
    owner_iid: str | None,
    origin: str = "monster_native",
) -> Optional[Dict[str, Any]]:
    """Mint an item instance for ``item_id`` and assign it to ``owner_iid``."""

    if not item_id:
        return None

    # If this item is going directly into an inventory, force it off-ground.
    if owner_iid is not None:
        year, x, y = -1, -1, -1
    elif isinstance(pos, Mapping):
        year = int(pos.get("year", 0) or 0)
        x = int(pos.get("x", 0) or 0)
        y = int(pos.get("y", 0) or 0)
    elif isinstance(pos, Sequence) and len(pos) >= 3:
        try:
            year, x, y = int(pos[0]), int(pos[1]), int(pos[2])
        except (TypeError, ValueError):
            year, x, y = 0, 0, 0
    else:
        # No owner and no pos provided: default to "nowhere"/off-ground until positioned explicitly.
        year, x, y = -1, -1, -1

    iid = mint_instance(str(item_id), origin=origin)
    try:
        updated = update_instance(
            iid,
            owner=str(owner_iid) if owner_iid is not None else None,
            year=year,
            x=x,
            y=y,
        )
    except KeyError:
        updated = None

    instance = updated if isinstance(updated, Mapping) else get_instance(iid)
    if not isinstance(instance, Mapping):
        return None

    payload = dict(instance)
    payload.setdefault("instance_id", iid)
    payload.setdefault("iid", iid)
    return payload


def bulk_add(instances: Iterable[Mapping[str, Any]]) -> List[str]:
    """Add ``instances`` to the registry ensuring normalization."""

    store = _items_store()
    added: List[str] = []

    for inst in instances:
        if isinstance(inst, MutableMapping):
            payload: Dict[str, Any] = dict(inst)
        else:
            payload = dict(inst)

        if "year" not in payload:
            payload["year"] = -1
        if "x" not in payload:
            payload["x"] = -1
        if "y" not in payload:
            payload["y"] = -1

        _normalize_instance(payload)

        while True:
            iid = str(payload.get("iid") or mint_iid())
            payload["iid"] = iid
            payload["instance_id"] = iid
            try:
                store.mint(_store_payload_from_instance(payload))
                added.append(iid)
                break
            except KeyError:
                payload.pop("iid", None)
                payload.pop("instance_id", None)
                continue

    return added


def update_instance(iid: str, **fields: Any) -> Dict[str, Any]:
    """Update ``iid`` with ``fields`` using direct DB updates (no snapshots)."""

    store = _items_store()
    siid = str(iid)

    # Normalise positional input
    pos = fields.pop("pos", None)
    to_set: Dict[str, Any] = {}
    if isinstance(pos, Mapping):
        pos = (pos.get("year"), pos.get("x"), pos.get("y"))
    if isinstance(pos, (list, tuple)) and len(pos) == 3:
        try:
            year_val = int(pos[0])
            x_val = int(pos[1])
            y_val = int(pos[2])
        except (TypeError, ValueError):
            pass
        else:
            to_set.update(year=year_val, x=x_val, y=y_val)

    # Explicit coordinates override position tuple
    if "year" in fields:
        try:
            to_set["year"] = int(fields["year"])
        except (TypeError, ValueError):
            pass
    if "x" in fields:
        try:
            to_set["x"] = int(fields["x"])
        except (TypeError, ValueError):
            pass
    if "y" in fields:
        try:
            to_set["y"] = int(fields["y"])
        except (TypeError, ValueError):
            pass

    # Enchantment / condition sanitisation
    if "enchant_level" in fields:
        value = fields.get("enchant_level")
        if value is REMOVE_FIELD:
            to_set["enchant"] = None
        else:
            level = _sanitize_enchant_level(value)
            to_set["enchant"] = level
    if "condition" in fields:
        if fields["condition"] is REMOVE_FIELD:
            to_set["condition"] = None
        else:
            to_set["condition"] = _sanitize_condition(fields.get("condition"))

    if "charges" in fields:
        value = fields.get("charges")
        if value is REMOVE_FIELD:
            to_set["charges"] = None
        else:
            try:
                to_set["charges"] = int(value)
            except (TypeError, ValueError):
                pass

    # Simple optional string fields
    for attr in ("owner", "origin", "drop_source"):
        if attr in fields:
            value = fields.get(attr)
            if value is REMOVE_FIELD:
                to_set[attr] = None
            elif isinstance(value, Mapping):
                try:
                    to_set[attr] = json.dumps(value, sort_keys=True)
                except Exception:
                    to_set[attr] = str(value)
            elif isinstance(value, str) and value.strip():
                to_set[attr] = value
            else:
                to_set[attr] = None

    if "created_at" in fields:
        value = fields.get("created_at")
        if value is REMOVE_FIELD:
            to_set["created_at"] = None
        else:
            try:
                to_set["created_at"] = int(value)
            except (TypeError, ValueError):
                pass

    # Preserve behaviour for arbitrary columns (e.g. charges)
    skip_keys = {
        "pos",
        "year",
        "x",
        "y",
        "enchant_level",
        "condition",
        "owner",
        "origin",
        "drop_source",
        "created_at",
    }
    for key, value in fields.items():
        if key in skip_keys:
            continue
        if value is REMOVE_FIELD:
            to_set[key] = None
        else:
            to_set[key] = value

    if to_set:
        try:
            store.update_fields(siid, **to_set)
        except KeyError:
            raise KeyError(iid) from None

    record = store.get_by_iid(siid)
    if record is None:
        raise KeyError(iid)
    return _inflate_store_record(record)


def remove_instance(iid: str) -> bool:
    """Remove ``iid`` from the registry returning True if it existed."""

    store = _items_store()
    try:
        store.delete(str(iid))
        return True
    except KeyError:
        return False


def move_instance(
    iid: str,
    *,
    src: Optional[Tuple[int, int, int]] = None,
    dest: Optional[Tuple[int, int, int]] = None,
) -> bool:
    """Move ``iid`` from ``src`` to ``dest`` verifying invariants."""

    store = _items_store()
    record = store.get_by_iid(str(iid))
    if record is None:
        return False

    inflated = _inflate_store_record(record)
    current = _pos_of(inflated)
    if src is not None and current != tuple(map(int, src)):
        return False

    if dest is None:
        try:
            store.update_fields(str(iid), year=-1, x=-1, y=-1)
        except KeyError:
            return False
    else:
        year, x, y = (int(dest[0]), int(dest[1]), int(dest[2]))
        try:
            store.move(str(iid), year=year, x=x, y=y)
        except KeyError:
            return False

    return True

def save_instances() -> None:
    """No-op: persistence is immediate via the SQLite store."""
    return None


def remove_instances(instance_ids: List[str]) -> int:
    """Remove all instances whose ids are in ``instance_ids``."""

    targets = {str(i) for i in instance_ids if i}
    if not targets:
        return 0

    store = _items_store()
    removed = 0
    for iid in targets:
        try:
            store.delete(iid)
            removed += 1
        except KeyError:
            continue
    return removed

def list_instances_at(year: int, x: int, y: int) -> List[Dict[str, Any]]:
    """Return cached instance payloads at ``(year, x, y)``."""

    store = _items_store()
    records = store.list_at(int(year), int(x), int(y))
    return [_inflate_store_record(rec) for rec in records]
def get_instance(iid: str) -> Optional[Dict[str, Any]]:
    """Return the cached instance matching ``iid`` if present."""

    store = _items_store()
    record = store.get_by_iid(str(iid))
    if record is None:
        return None
    return _inflate_store_record(record)


def delete_instance(iid: str) -> int:
    """Remove the instance identified by ``iid`` from the cache and persist."""

    return int(remove_instance(iid))


def get_enchant_level(iid: str) -> int:
    """Return the normalised enchant level for ``iid``."""

    inst = get_instance(iid)
    if not inst:
        return 0
    level = _sanitize_enchant_level(inst.get("enchant_level"))
    if inst.get("enchant_level") != level:
        inst["enchant_level"] = level
    return level


def is_enchanted(iid: str) -> bool:
    """Return ``True`` when ``iid`` has any enchantment bonus."""

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
    """Return the clamped condition value for ``iid``."""

    inst = get_instance(iid)
    if not inst:
        return 0
    if _is_broken_instance(inst):
        try:
            _items_store().update_fields(str(iid), condition=None)
        except KeyError:
            pass
        return 0
    condition = _sanitize_condition(inst.get("condition"))
    if inst.get("condition") != condition:
        try:
            _items_store().update_fields(str(iid), condition=condition)
        except KeyError:
            pass
    return condition


def set_condition(iid: str, value: int) -> int:
    """Set ``iid`` condition to ``value`` respecting invariants."""

    inst = get_instance(iid)
    if not inst:
        raise KeyError(iid)
    if is_enchanted(iid):
        return get_condition(iid)
    if _is_broken_instance(inst):
        try:
            _items_store().update_fields(str(iid), condition=None)
        except KeyError:
            pass
        return 0
    amount = _sanitize_condition(value)
    _items_store().update_fields(str(iid), condition=amount)
    return amount


def crack_instance(iid: str) -> Optional[Dict[str, Any]]:
    """Mark ``iid`` as broken and return the mutated payload."""

    inst = get_instance(iid)
    if not inst:
        return None

    current_item_id = _item_id(inst)
    catalog = items_catalog.load_catalog()
    tpl = catalog.get(current_item_id) if catalog else None
    is_armour = bool(tpl.get("armour")) if isinstance(tpl, dict) else False
    new_item_id = BROKEN_ARMOUR_ID if is_armour else BROKEN_WEAPON_ID
    store = _items_store()
    try:
        store.update_fields(str(iid), item_id=new_item_id, condition=None)
    except KeyError:
        return None
    return get_instance(iid)


def snapshot_instances() -> List[Dict[str, Any]]:
    """Return a shallow copy of the cached instances list."""

    store = _items_store()
    return [_inflate_store_record(rec) for rec in store.snapshot()]


def clear_position(iid: str) -> None:
    """Back-compat: clear by iid (may hit wrong object if duplicate iids exist)."""

    try:
        _items_store().update_fields(str(iid), year=-1, x=-1, y=-1)
    except KeyError:
        return


def clear_position_at(iid: str, year: int, x: int, y: int) -> bool:
    """Preferred: clear only if the iid currently resides at (year, x, y)."""

    record = _items_store().get_by_iid(str(iid))
    if record is None:
        return False

    inst = _inflate_store_record(record)
    target = (int(year), int(x), int(y))
    current = _pos_of(inst)
    if current != target:
        LOG.error(
            "[itemsdbg] CLEAR_AT_MISS iid=%s not at (%s,%s,%s); no change",
            iid,
            year,
            x,
            y,
        )
        return False

    try:
        _items_store().update_fields(str(iid), year=-1, x=-1, y=-1)
    except KeyError:
        return False
    return True

def set_position(iid: str, year: int, x: int, y: int) -> None:
    """Set the position of ``iid`` to ``(year, x, y)`` and persist."""

    _items_store().move(str(iid), year=int(year), x=int(x), y=int(y))


def create_and_save_instance(item_id: str, year: int, x: int, y: int, origin: str = "debug_add") -> str:
    """Create a new instance at ``(year, x, y)`` and persist it."""
    store = _items_store()

    inst: Dict[str, Any] = {
        "iid": "",
        "item_id": str(item_id),
        "origin": origin,
        "year": int(year),
        "x": int(x),
        "y": int(y),
    }

    _apply_catalog_defaults(inst)
    inst.setdefault("enchant_level", 0)
    inst.setdefault("condition", 100)
    inst.setdefault("god_tier", False)

    while True:
        mint = mint_iid()
        inst["iid"] = mint
        inst["pos"] = {"year": int(year), "x": int(x), "y": int(y)}
        _normalize_instance(inst)
        try:
            store.mint(_store_payload_from_instance(inst))
            return mint
        except KeyError:
            continue


class ItemsInstancesFacade:
    """Light-weight facade exposing runtime helpers for item instances."""

    def mint_item(
        self,
        *,
        item_id: str,
        pos: Sequence[int] | Mapping[str, Any] | None,
        owner_iid: str | None,
        origin: str = "monster_native",
    ) -> Optional[Dict[str, Any]]:
        return mint_item(item_id=item_id, pos=pos, owner_iid=owner_iid, origin=origin)


ItemsInstances = ItemsInstancesFacade
_FACADE = ItemsInstancesFacade()


def get() -> ItemsInstancesFacade:
    """Return a process-wide facade for item instance helpers."""

    return _FACADE

