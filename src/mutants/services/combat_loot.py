from __future__ import annotations

from typing import Iterable, Mapping, Sequence

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


def drop_new_entries(
    entries: Iterable[Mapping[str, object]],
    pos: tuple[int, int, int],
    *,
    origin: str = "monster_drop",
) -> list[str]:
    year, x, y = pos
    minted: list[str] = []
    for entry in entries:
        item_id = _resolve_item_id(entry)
        if not item_id:
            continue

        iid_raw = entry.get("iid") or entry.get("instance_id")
        iid = str(iid_raw).strip() if iid_raw else ""
        existing = itemsreg.get_instance(iid) if iid else None
        if existing is None:
            entry_origin = entry.get("origin")
            origin_value = (
                str(entry_origin)
                if isinstance(entry_origin, str) and entry_origin
                else origin
            )
            iid = itemsreg.mint_instance(item_id, origin_value)
        else:
            iid = str(existing.get("iid") or existing.get("instance_id") or iid)

        updates: dict[str, object] = {
            "item_id": item_id,
            "pos": {"year": year, "x": x, "y": y},
            "year": year,
            "x": x,
            "y": y,
        }

        enchant = max(0, _coerce_int(entry.get("enchant_level"), 0))
        updates["enchant_level"] = enchant
        updates["enchanted"] = "yes" if enchant > 0 else "no"

        condition = entry.get("condition")
        if condition is None:
            if enchant > 0:
                updates["condition"] = itemsreg.REMOVE_FIELD
            elif existing is None:
                updates["condition"] = 100
        else:
            updates["condition"] = max(0, _coerce_int(condition, 0))

        tags = entry.get("tags")
        if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
            updates["tags"] = [str(tag) for tag in tags if isinstance(tag, str) and tag]

        if entry.get("notes") is not None:
            updates["notes"] = entry.get("notes")

        entry_origin = entry.get("origin")
        if isinstance(entry_origin, str) and entry_origin:
            updates["origin"] = str(entry_origin)
        elif existing is None or not existing.get("origin"):
            updates["origin"] = origin

        itemsreg.update_instance(iid, **updates)
        minted.append(iid)

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
        moved = itemsreg.move_instance(iid, dest=(year, x, y))
        if moved:
            inst = itemsreg.get_instance(iid)
            dropped.append(str(inst.get("iid") if inst else iid))
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
            itemsreg.remove_instance(iid)
            removed.append(iid)
            overflow -= 1
            if hasattr(bus, "push"):
                bus.push("COMBAT/INFO", f"There is no room for {label}; it vaporizes.")
        idx -= 1
    return removed

