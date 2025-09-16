from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from mutants.ui.item_display import item_label

try:  # pragma: no cover - defensive import for optional catalog
    from mutants.registries import items_catalog
except Exception:  # pragma: no cover - catalog may be unavailable in tests
    items_catalog = None  # type: ignore[assignment]


def render_inventory_final(player: dict, items_reg: Any) -> Tuple[List[str], int]:
    """Render the final BBS-style inventory list.

    Args:
        player: Player dictionary obtained from ``StateManager.get_active().to_dict()``.
        items_reg: Items registry providing optional lookup helpers.

    Returns:
        A tuple ``(lines, total_weight_lb)``. ``lines`` contains either
        ``["Nothing."]`` when the inventory is empty or one line per item name.
        ``total_weight_lb`` is the integer total of the weights (unknown weights
        count as ``0``).
    """

    raw_inventory = player.get("inventory")
    if isinstance(raw_inventory, Iterable) and not isinstance(raw_inventory, (str, bytes, dict)):
        inventory = list(raw_inventory)
    elif raw_inventory:
        inventory = [raw_inventory]
    else:
        inventory = []

    lines: List[str] = []
    total = 0

    catalog: Optional[Any] = None
    catalog_failed = False

    def _load_catalog():
        nonlocal catalog, catalog_failed
        if catalog_failed:
            return None
        if catalog is None:
            if items_catalog is None:
                catalog_failed = True
                return None
            try:
                catalog = items_catalog.load_catalog()
            except Exception:
                catalog_failed = True
                catalog = None
        return catalog

    def _coerce_iid(entry: Any) -> Any:
        if isinstance(entry, dict):
            for key in ("id", "iid", "instance_id", "item_id", "name"):
                value = entry.get(key)
                if value:
                    return value
        return entry

    def _resolve_instance(iid: Any) -> Optional[Dict[str, Any]]:
        if items_reg is None:
            return None
        fn = getattr(items_reg, "get_instance", None)
        if callable(fn):
            try:
                inst = fn(iid)
                if isinstance(inst, dict):
                    return inst
            except Exception:
                return None
        return None

    def _resolve_template(inst: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(inst, dict):
            return None
        item_id = inst.get("item_id")
        if not item_id:
            return None
        cat = _load_catalog()
        if cat is None:
            return None
        try:
            tpl = cat.get(str(item_id))  # type: ignore[call-arg]
        except Exception:
            tpl = None
        if isinstance(tpl, dict):
            return tpl
        return None

    def _name(iid: Any, inst: Optional[Dict[str, Any]], tpl: Optional[Dict[str, Any]]) -> str:
        for attr in ("get_display_name", "display_name", "name_of", "describe"):
            fn = getattr(items_reg, attr, None)
            if callable(fn):
                try:
                    val = fn(iid)
                    if isinstance(val, dict):
                        name = val.get("name")
                        if name:
                            return str(name)
                    elif val is not None:
                        return str(val)
                except Exception:
                    pass
        if tpl or inst:
            try:
                return item_label(inst or {}, tpl or {}, show_charges=False)
            except Exception:
                pass
            if tpl:
                for key in ("display_name", "name", "title"):
                    value = tpl.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        if inst:
            for key in ("display_name", "name"):
                value = inst.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return str(iid)

    def _weight(
        iid: Any,
        inst: Optional[Dict[str, Any]],
        tpl: Optional[Dict[str, Any]],
        entry: Any,
    ) -> int:
        for attr in ("weight_lb", "get_weight_lb", "describe"):
            fn = getattr(items_reg, attr, None)
            if callable(fn):
                try:
                    val = fn(iid)
                    if isinstance(val, dict):
                        cand = val.get("weight_lb")
                        if cand is not None:
                            return int(cand)
                    else:
                        return int(val)
                except Exception:
                    pass
        if inst:
            for key in ("weight_lb", "weight"):
                cand = inst.get(key)
                if cand is not None:
                    try:
                        return int(cand)
                    except Exception:
                        continue
        if tpl:
            for key in ("weight_lb", "weight"):
                cand = tpl.get(key)
                if cand is not None:
                    try:
                        return int(cand)
                    except Exception:
                        continue
        if isinstance(entry, dict):
            for key in ("weight_lb", "weight"):
                cand = entry.get(key)
                if cand is not None:
                    try:
                        return int(cand)
                    except Exception:
                        continue
        return 0

    if not inventory:
        return (["Nothing."], 0)

    for entry in inventory:
        iid = _coerce_iid(entry)
        inst = _resolve_instance(iid)
        tpl = _resolve_template(inst)
        nm = _name(iid, inst, tpl)
        wt = _weight(iid, inst, tpl, entry)
        lines.append(nm)
        total += max(0, wt)

    return (lines, total)
