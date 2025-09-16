from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Callable

from mutants.registries import items_catalog, items_instances as itemsreg
from .item_display import item_label, number_duplicates, with_article
from .textutils import harden_final_display
from .wrap import wrap_list

DEFAULT_EXCLUDE_SLOTS: frozenset[str] = frozenset({'armor'})

CatalogLike = Any
InstanceResolver = Callable[[str], Any]


def _call_maybe(fn: Callable[[], CatalogLike] | None) -> CatalogLike | None:
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def _coerce_quantity(raw: Any) -> float:
    try:
        if raw is None:
            return 1.0
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


def _coerce_weight(raw: Any) -> float:
    try:
        if raw is None:
            return 0.0
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _truthy(raw: Any) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() not in {'', 'false', 'no', '0'}
    return bool(raw)


def _catalog_from_ctx(ctx: Any) -> CatalogLike:
    if isinstance(ctx, Mapping):
        candidate = ctx.get('items_catalog')
        if candidate is not None:
            if callable(candidate):
                resolved = _call_maybe(candidate)  # type: ignore[arg-type]
                if resolved is not None:
                    return resolved
            else:
                return candidate
        loader = ctx.get('items_catalog_loader')
        resolved = _call_maybe(loader) if callable(loader) else None
        if resolved is not None:
            return resolved
        registries = ctx.get('registries')
        if isinstance(registries, Mapping):
            candidate = registries.get('items_catalog')
            if candidate is not None:
                if callable(candidate):
                    resolved = _call_maybe(candidate)  # type: ignore[arg-type]
                    if resolved is not None:
                        return resolved
                else:
                    return candidate
    try:
        return items_catalog.load_catalog()
    except Exception:
        return {}


def _instance_resolver_from_ctx(ctx: Any) -> InstanceResolver:
    if isinstance(ctx, Mapping):
        resolver = ctx.get('items_instance_resolver')
        if callable(resolver):
            return resolver
        items_obj = ctx.get('items')
        getter = getattr(items_obj, 'get_instance', None)
        if callable(getter):
            return getter  # type: ignore[return-value]
        registries = ctx.get('registries')
        if isinstance(registries, Mapping):
            inst_reg = registries.get('items_instances')
            getter = getattr(inst_reg, 'get_instance', None)
            if callable(getter):
                return getter  # type: ignore[return-value]
    return itemsreg.get_instance


def _lookup_template(catalog: CatalogLike, item_id: Any) -> dict[str, Any]:
    if not item_id:
        return {}
    key = str(item_id)
    if isinstance(catalog, Mapping):
        tpl = catalog.get(key)
        return tpl if isinstance(tpl, Mapping) else {}
    getter = getattr(catalog, 'get', None)
    if callable(getter):
        try:
            tpl = getter(key)
        except Exception:
            return {}
        return tpl if isinstance(tpl, Mapping) else {}
    return {}


def _resolve_entry(entry: Any, resolver: InstanceResolver) -> dict[str, Any]:
    inst_data: dict[str, Any] = {}
    entry_dict = entry if isinstance(entry, Mapping) else None
    inst_id: Any = None
    if entry_dict is not None:
        for key in ('iid', 'instance_id', 'id'):
            val = entry_dict.get(key)
            if val:
                inst_id = val
                break
    elif entry is not None:
        inst_id = entry
    resolved: Any = None
    if inst_id is not None and callable(resolver):
        try:
            resolved = resolver(str(inst_id))
        except Exception:
            resolved = None
    if isinstance(resolved, Mapping):
        inst_data.update(resolved)
    if entry_dict is not None:
        inst_data.update(entry_dict)
    if isinstance(inst_id, str) and 'instance_id' not in inst_data:
        inst_data['instance_id'] = inst_id
    return inst_data


def _should_exclude(inst: Mapping[str, Any], exclude_slots: set[str]) -> bool:
    if not exclude_slots:
        return False
    if not _truthy(inst.get('equipped')):
        return False
    slot = inst.get('slot')
    if slot is None:
        return False
    return str(slot) in exclude_slots


def _iter_entries(inv_instances: Any) -> list[Any]:
    if inv_instances is None:
        return []
    if isinstance(inv_instances, list):
        return inv_instances
    if isinstance(inv_instances, tuple):
        return list(inv_instances)
    if isinstance(inv_instances, set):
        return list(inv_instances)
    if isinstance(inv_instances, Iterable) and not isinstance(inv_instances, (str, bytes, Mapping)):
        return list(inv_instances)
    return [inv_instances]


def render_inventory_section(
    ctx: Any,
    inv_instances: Any,
    *,
    show_header: bool = True,
    exclude_equipped_slots: Iterable[str] | None = None,
) -> list[str]:
    """Return lines describing *inv_instances* using the inventory format."""

    raw_exclude = (
        exclude_equipped_slots if exclude_equipped_slots is not None else DEFAULT_EXCLUDE_SLOTS
    )
    exclude_slots = {str(slot) for slot in raw_exclude if slot is not None}

    catalog = _catalog_from_ctx(ctx)
    resolver = _instance_resolver_from_ctx(ctx)

    names: list[str] = []
    total_weight = 0.0

    for entry in _iter_entries(inv_instances):
        inst = _resolve_entry(entry, resolver)
        if _should_exclude(inst, exclude_slots):
            continue

        item_id = inst.get('item_id')
        if item_id is None:
            for alt_key in ('catalog_id', 'id'):
                alt = inst.get(alt_key)
                if alt:
                    item_id = alt
                    break
        tpl = _lookup_template(catalog, item_id)

        label = item_label(inst, tpl, show_charges=False)
        names.append(str(label))

        qty = _coerce_quantity(inst.get('quantity'))
        weight_val = _coerce_weight(tpl.get('weight') if isinstance(tpl, Mapping) else None)
        total_weight += weight_val * qty

    rounded_total = round(total_weight)
    lines: list[str] = []
    if show_header:
        lines.append(
            f"You are carrying the following items: (Total Weight: {rounded_total} LB's)"
        )

    if not names:
        lines.append('Nothing.')
        return lines

    numbered = number_duplicates(names)
    display = [harden_final_display(with_article(name)) for name in numbered]
    lines.extend(wrap_list(display))
    return lines
