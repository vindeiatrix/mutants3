from __future__ import annotations

import copy
import logging
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from mutants.registries import items_instances as itemsreg
from mutants.services.item_transfer import GROUND_CAP
from mutants.ui.item_display import item_label


LOG_DEV = logging.getLogger("mutants.playersdbg")


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
    """Return ``(year, x, y)`` when ``value`` looks like positional data."""

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
    """Mint entries at ``pos`` and return their instance IDs."""

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
    """Move existing ``iids`` to ``pos`` and return the resolved IDs."""

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
    """Spawn the mandatory skull drop at ``pos``."""

    return drop_new_entries([{"item_id": "skull"}], pos, origin=origin)


def _instance_label(inst: Mapping[str, object] | None, catalog: Mapping[str, Mapping[str, object]] | None) -> str:
    if not inst:
        return "the item"
    item_id = str(inst.get("item_id") or inst.get("catalog_id") or inst.get("id") or "item")
    template = catalog.get(item_id) if isinstance(catalog, Mapping) else {}
    return item_label(inst, template or {}, show_charges=False)


def _entry_label(entry: Mapping[str, object] | None, catalog: Mapping[str, Mapping[str, object]] | None) -> str:
    if not entry:
        return "the item"
    item_id = str(entry.get("item_id") or entry.get("catalog_id") or entry.get("id") or "item")
    template = catalog.get(item_id) if isinstance(catalog, Mapping) else {}
    return item_label(entry, template or {}, show_charges=False)


def _clone_entry(entry: Mapping[str, object] | None, *, source: str) -> dict[str, object]:
    payload = copy.deepcopy(entry) if isinstance(entry, Mapping) else {}
    payload.setdefault("item_id", str(payload.get("item_id") or payload.get("catalog_id") or payload.get("id") or ""))
    payload["drop_source"] = source
    return payload


def describe_vaporized_entries(
    entries: Sequence[Mapping[str, object]] | None,
    *,
    catalog: Mapping[str, Mapping[str, object]] | None = None,
) -> list[str]:
    """Return player-facing messages for ``entries`` that vaporised."""

    if not entries:
        return []

    messages: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        label = _entry_label(entry, catalog)
        messages.append(f"There is no room for {label}; it vaporizes.")
    return messages


def drop_monster_loot(
    *,
    pos: tuple[int, int, int],
    bag_entries: Sequence[Mapping[str, object]] | None,
    armour_entry: Mapping[str, object] | None,
    bus=None,
    catalog: Mapping[str, Mapping[str, object]] | None = None,
    sorted_bag_entries: Sequence[Mapping[str, object]] | None = None,
    drop_summary: MutableMapping[str, Any] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Drop monster loot respecting ground capacity and deterministic order.

    Parameters
    ----------
    pos
        Coordinates where drops should appear.
    bag_entries
        Iterable of item payloads sourced from the monster's inventory.
    sorted_bag_entries
        Optional pre-sorted sequence of bag entries. When provided it takes
        precedence over ``bag_entries`` for establishing the drop order.
    armour_entry
        Optional armour payload to drop.
    bus
        Event emitter for logging loot events.
    catalog
        Optional catalog mapping used for labels.
    drop_summary
        Optional mapping populated with diagnostic information describing the
        resolved drop order and any items that vaporised.

    Returns
    -------
    tuple[list[dict[str, object]], list[dict[str, object]]]
        ``(minted, vaporized)`` payloads annotated with ``drop_source``.
    """

    attempts: list[tuple[str, Mapping[str, object]]] = []
    bag_iterable: Sequence[Mapping[str, object]] | None
    if sorted_bag_entries:
        bag_iterable = [entry for entry in sorted_bag_entries if isinstance(entry, Mapping)]
    else:
        bag_iterable = [entry for entry in bag_entries or [] if isinstance(entry, Mapping)]

    for entry in bag_iterable:
        attempts.append(("bag", entry))
    skull_entry: Mapping[str, object] = {"item_id": "skull"}
    attempts.append(("skull", skull_entry))
    if isinstance(armour_entry, Mapping):
        attempts.append(("armour", armour_entry))

    year, x, y = pos
    ground = itemsreg.list_instances_at(year, x, y)
    free_slots = max(0, GROUND_CAP - len(ground))

    minted: list[dict[str, object]] = []
    vaporized: list[dict[str, object]] = []
    summary_messages: list[str] = []
    summary_attempt_order: list[str] = []

    if free_slots <= 0 and attempts:
        LOG_DEV.info(
            "[playersdbg] MON-DROP-VAP pos=%s reason=ground-full attempts=%s",
            list(pos),
            len(attempts),
        )
        for source, entry in attempts:
            vaporized.append(_clone_entry(entry, source=source))
            summary_attempt_order.append(source)
        summary_messages.extend(describe_vaporized_entries(vaporized, catalog=catalog))
        if summary_messages and hasattr(bus, "push"):
            for message in summary_messages:
                bus.push("COMBAT/INFO", message)
        if isinstance(drop_summary, MutableMapping):
            drop_summary["pos"] = {"year": year, "x": x, "y": y}
            drop_summary["attempt_order"] = summary_attempt_order
            drop_summary["minted"] = minted
            drop_summary["vaporized"] = vaporized
            drop_summary["messages"] = summary_messages
        return minted, vaporized

    for source, entry in attempts:
        summary_attempt_order.append(source)
        if free_slots <= 0:
            vaporized.append(_clone_entry(entry, source=source))
            message = describe_vaporized_entries([entry], catalog=catalog)
            if message:
                summary_messages.extend(message)
                if hasattr(bus, "push"):
                    bus.push("COMBAT/INFO", message[0])
            continue

        minted_iids = drop_new_entries([entry], pos)
        if not minted_iids:
            continue
        iid = minted_iids[-1]
        record = _clone_entry(entry, source=source)
        record["iid"] = iid
        if record.get("item_id"):
            # Ensure canonical item id when the original entry omitted it.
            inst = itemsreg.get_instance(iid)
            if inst and inst.get("item_id"):
                record["item_id"] = str(inst.get("item_id"))
        minted.append(record)
        free_slots -= 1

    if isinstance(drop_summary, MutableMapping):
        drop_summary["pos"] = {"year": year, "x": x, "y": y}
        drop_summary["attempt_order"] = summary_attempt_order
        drop_summary["minted"] = minted
        drop_summary["vaporized"] = vaporized
        drop_summary["messages"] = summary_messages

    return minted, vaporized


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

