from __future__ import annotations

from typing import Any, Mapping, Optional

from mutants.registries import items_instances


def _coerce_charges(value: Any) -> int:
    """Return a non-negative integer number of charges from ``value``."""

    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, as_int)


def charges_for_instance(inst: Optional[Mapping[str, Any]]) -> int:
    """Return the available charges for ``inst``.

    The value is always derived from the instance record rather than the
    catalog defaults so that it reflects the state stored in the database.
    """

    if not inst:
        return 0
    return _coerce_charges(inst.get("charges"))


def consume_charge(iid: str, *, charges: Optional[int] = None) -> int:
    """Persist a single charge consumption for ``iid``.

    ``charges`` can be provided when already known to avoid reloading the
    instance. The function always persists the updated value using the items
    store so that subsequent lookups observe the decrement.
    """

    current = _coerce_charges(charges)
    if charges is None:
        inst = items_instances.get_instance(iid)
        current = charges_for_instance(inst)

    if current <= 0:
        return current

    next_value = current - 1
    store = items_instances._items_store()
    store.update_fields(str(iid), charges=next_value)
    return next_value
