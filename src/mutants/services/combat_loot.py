from __future__ import annotations

import uuid
from typing import Iterable, Mapping, MutableMapping, Sequence

from mutants.registries import items_instances as itemsreg
from mutants.services.item_transfer import GROUND_CAP
from mutants.ui.item_display import item_label


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_item_id(entry: Mapping[str, object]) -> str:
    for key in ("item_id", "catalog_id", "id"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw:
            return raw
        if raw is not None:
            return str(raw)
    return ""


def coerce_pos(value, fallback: tuple[int, int, int] | None = None) -> tuple[int, int, int] | None:
    if isinstance(value, Mapping):
        coords: Sequence[object] = (
            value.get("year"),
            value.get("x"),
            value.get("y"),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        coords = value
    else:
        return fallback

    if len(coords) != 3:
        return fallback

    try:
        year, x, y = int(coords[0]), int(coords[1]), int(coords[2])
    except (TypeError, ValueError):
        return fallback
    return year, x, y


def _persist_instances() -> None:
    try:
        itemsreg.save_instances()
    except Exception:
        # Persist best-effort; failures are logged by registry helpers.
        pass


def drop_new_entries(
    entries: Iterable[Mapping[str, object]],
    pos: tuple[int, int, int],
    *,
    origin: str = "monster_drop",
) -> list[str]:
    year, x, y = pos
    minted: list[str] = []
    raw = itemsreg._cache()  # type: ignore[attr-defined]
    for entry in entries:
        item_id = _resolve_item_id(entry)
        if not item_id:
            continue

        iid_raw = entry.get("iid") or entry.get("instance_id")
        iid = str(iid_raw).strip() if iid_raw else ""
        inst: MutableMapping[str, object] | None = itemsreg.get_instance(iid) if iid else None
        if inst is None:
            minted_iid = f"{item_id or 'loot'}#{uuid.uuid4().hex[:8]}"
            inst = {"iid": minted_iid, "instance_id": minted_iid, "origin": origin}
            raw.append(inst)
            iid = minted_iid
        else:
            iid = str(inst.get("iid") or inst.get("instance_id") or iid)

        inst["item_id"] = item_id
        enchant = max(0, _coerce_int(entry.get("enchant_level"), 0))
        inst["enchant_level"] = enchant
        inst["enchanted"] = "yes" if enchant > 0 else "no"

        condition = entry.get("condition")
        if condition is None and enchant > 0:
            inst.pop("condition", None)
        elif condition is not None:
            inst["condition"] = max(0, _coerce_int(condition, 0))
        else:
            inst.setdefault("condition", 100)

        tags = entry.get("tags")
        if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
            inst["tags"] = [str(tag) for tag in tags if isinstance(tag, str) and tag]

        if entry.get("notes") is not None:
            inst["notes"] = entry.get("notes")

        inst.setdefault("origin", origin)
        inst["pos"] = {"year": year, "x": x, "y": y}
        inst["year"] = year
        inst["x"] = x
        inst["y"] = y
        minted.append(iid)

    _persist_instances()
    return minted


def drop_existing_iids(iids: Iterable[str], pos: tuple[int, int, int]) -> list[str]:
    year, x, y = pos
    dropped: list[str] = []
    for iid in iids:
        if not iid:
            continue
        inst = itemsreg.get_instance(iid)
        if not inst:
            continue
        itemsreg.set_position(iid, year, x, y)
        inst["pos"] = {"year": year, "x": x, "y": y}
        inst["year"] = year
        inst["x"] = x
        inst["y"] = y
        dropped.append(str(inst.get("iid") or iid))

    if dropped:
        _persist_instances()
    return dropped


def spawn_skull(pos: tuple[int, int, int], *, origin: str = "monster_drop") -> list[str]:
    return drop_new_entries([{"item_id": "skull"}], pos, origin=origin)


def _instance_label(inst: Mapping[str, object] | None, catalog: Mapping[str, Mapping[str, object]] | None) -> str:
    if not inst:
        return "the item"
    item_id = str(inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or "item")
    template = catalog.get(item_id) if isinstance(catalog, Mapping) else {}
    return item_label(inst, template or {}, show_charges=False)


def enforce_capacity(
    pos: tuple[int, int, int],
    new_iids: Iterable[str],
    *,
    bus=None,
    catalog: Mapping[str, Mapping[str, object]] | None = None,
) -> list[str]:
    year, x, y = pos
    ground = itemsreg.list_instances_at(year, x, y)
    overflow = len(ground) - GROUND_CAP
    if overflow <= 0:
        return []

    candidates = [iid for iid in new_iids if iid]
    removed: list[str] = []
    idx = len(candidates) - 1
    while overflow > 0 and idx >= 0:
        iid = candidates[idx]
        inst = itemsreg.get_instance(iid)
        if inst:
            label = _instance_label(inst, catalog)
            itemsreg.delete_instance(iid)
            removed.append(iid)
            overflow -= 1
            if hasattr(bus, "push"):
                bus.push("COMBAT/INFO", f"There is no room for {label}; it vaporizes.")
        idx -= 1

    if removed:
        _persist_instances()
    return removed

