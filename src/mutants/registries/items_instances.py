from __future__ import annotations

import inspect
import logging
import os
import uuid
from collections.abc import MutableSet
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

# NOTE: Imported by ``mutants.registries.json_store`` via :func:`get_stores`.

from mutants.state import state_path
from .storage import get_stores
from . import items_catalog

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
    store = get_stores().items
    items = [dict(inst) for inst in store.snapshot()]

    duplicates = _detect_duplicate_iids(items)
    _handle_duplicates(duplicates, strict=strict)

    _normalize_instances(items)

    return items


def _save_instances_raw(instances: List[Dict[str, Any]]) -> None:
    """Persist *instances* via the configured backend."""

    store = get_stores().items
    store.replace_all(instances)
    invalidate_cache()


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


def recharge_full(iid: str) -> int:
    """Recharge ``iid`` to full and return the amount of charge restored."""
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


def _ensure_internal_access() -> None:
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None:
        return
    module_name = frame.f_back.f_globals.get("__name__")
    assert module_name == __name__, "_cache() is private to items_instances"


def invalidate_cache() -> None:
    """Clear the cached snapshot forcing the next read to hit disk."""
    global _CACHE
    _CACHE = None


def _cache() -> List[Dict[str, Any]]:
    _ensure_internal_access()
    global _CACHE

    if _CACHE is None:
        _CACHE = _load_instances_raw()

    _normalize_instances(_CACHE)
    return _CACHE


def _ensure_iid(payload: MutableMapping[str, Any], seen: set[str]) -> str:
    iid = _instance_id(payload)
    if iid and iid not in seen:
        payload["iid"] = iid
        payload["instance_id"] = iid
        return iid

    iid = mint_iid(seen=seen)
    payload["iid"] = iid
    payload["instance_id"] = iid
    return iid


def mint_instance(item_id: str, origin: str = "unknown") -> str:
    """Create, persist, and return a new instance for ``item_id``."""

    raw = _cache()
    seen: set[str] = {iid for iid in (_instance_id(inst) for inst in raw) if iid}
    iid = mint_iid(seen=seen)

    template: Mapping[str, Any] | None = None
    try:
        catalog = items_catalog.load_catalog()
    except FileNotFoundError:
        catalog = None
    if catalog is not None and hasattr(catalog, "get"):
        maybe = catalog.get(str(item_id))  # type: ignore[call-arg]
        if isinstance(maybe, Mapping):
            template = maybe

    inst: Dict[str, Any] = {
        "iid": iid,
        "instance_id": iid,
        "item_id": str(item_id),
        "origin": str(origin),
        "enchant_level": 0,
        "enchanted": "no",
        "condition": 100,
        "god_tier": False,
    }

    if isinstance(template, Mapping):
        if int(template.get("charges_max", 0) or 0) > 0:
            inst["charges"] = int(template.get("charges_max", 0) or 0)
        if "god_tier" in template:
            inst["god_tier"] = _coerce_bool(template.get("god_tier"))

    _normalize_instance(inst)
    raw.append(inst)
    _save_instances_raw(raw)
    return iid


def bulk_add(instances: Iterable[Mapping[str, Any]]) -> List[str]:
    """Add ``instances`` to the registry ensuring normalization."""

    raw = _cache()
    seen: set[str] = {iid for iid in (_instance_id(inst) for inst in raw) if iid}
    added: List[str] = []

    for inst in instances:
        if isinstance(inst, MutableMapping):
            payload: Dict[str, Any] = dict(inst)
        else:
            payload = dict(inst)
        iid = _ensure_iid(payload, seen)
        seen.add(iid)
        _normalize_instance(payload)
        raw.append(payload)
        added.append(iid)

    if added:
        _save_instances_raw(raw)
    return added


def update_instance(iid: str, **fields: Any) -> Dict[str, Any]:
    """Update ``iid`` with ``fields`` ensuring normalization and persistence."""

    raw = _cache()
    target: Optional[Dict[str, Any]] = None
    siid = str(iid)
    for inst in raw:
        inst_id = str(inst.get("iid") or inst.get("instance_id") or "")
        if inst_id == siid:
            target = inst
            break

    if target is None:
        raise KeyError(iid)

    for key, value in fields.items():
        if value is REMOVE_FIELD:
            target.pop(key, None)
        else:
            target[key] = value
    _normalize_instance(target)
    _save_instances_raw(raw)
    return target


def remove_instance(iid: str) -> bool:
    """Remove ``iid`` from the registry returning True if it existed."""

    raw = _cache()
    siid = str(iid)
    before = len(raw)
    raw[:] = [inst for inst in raw if str(inst.get("iid") or inst.get("instance_id") or "") != siid]
    removed = before != len(raw)
    if removed:
        _save_instances_raw(raw)
    return removed


def move_instance(
    iid: str,
    *,
    src: Optional[Tuple[int, int, int]] = None,
    dest: Optional[Tuple[int, int, int]] = None,
) -> bool:
    """Move ``iid`` from ``src`` to ``dest`` verifying invariants."""

    raw = _cache()
    target: Optional[Dict[str, Any]] = None
    siid = str(iid)
    for inst in raw:
        inst_id = str(inst.get("iid") or inst.get("instance_id") or "")
        if inst_id == siid:
            target = inst
            break

    if target is None:
        return False

    current = _pos_of(target)
    if src is not None and current != tuple(map(int, src)):
        return False

    if dest is None:
        target.pop("pos", None)
        target["year"] = -1
        target["x"] = -1
        target["y"] = -1
    else:
        year, x, y = (int(dest[0]), int(dest[1]), int(dest[2]))
        target["pos"] = {"year": year, "x": x, "y": y}
        target["year"] = year
        target["x"] = x
        target["y"] = y

    _normalize_instance(target)
    _save_instances_raw(raw)
    return True

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
    """Return cached instance payloads at ``(year, x, y)``."""

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
        inst.pop("condition", None)
        return 0
    condition = _sanitize_condition(inst.get("condition"))
    if inst.get("condition") != condition:
        inst["condition"] = condition
    return condition


def set_condition(iid: str, value: int) -> int:
    """Set ``iid`` condition to ``value`` respecting invariants."""

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
    """Mark ``iid`` as broken and return the mutated payload."""

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
    """Set the position of ``iid`` to ``(year, x, y)`` and persist."""

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
    """Create a new instance at ``(year, x, y)`` and persist it."""
    raw = _cache()
    mint = mint_iid()
    inst = {
        "iid": mint,
        "item_id": str(item_id),
        "pos": {"year": int(year), "x": int(x), "y": int(y)},
        "year": int(year),
        "x": int(x),
        "y": int(y),
        "origin": origin,
        "enchant_level": 0,
        "condition": 100,
        "god_tier": False,
    }
    cat = items_catalog.load_catalog()
    tpl = cat.get(str(item_id)) if cat else None
    if tpl and int(tpl.get("charges_max", 0) or 0) > 0:
        inst["charges"] = int(tpl.get("charges_max"))
    if tpl:
        inst["god_tier"] = _coerce_bool(tpl.get("god_tier"))
    _normalize_instance(inst)
    raw.append(inst)
    _save_instances_raw(raw)
    return mint

