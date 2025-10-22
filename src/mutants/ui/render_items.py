"""Helpers for rendering item display names safely."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .textutils import harden_final_display


def harden_display_nonbreak(s: str) -> str:
    """Backward compat wrapper for :func:`harden_final_display`."""

    return harden_final_display(s)


def _render_items_on_ground(
    items: Any,
    year: int,
    x: int,
    y: int,
) -> Sequence[Mapping[str, Any]]:
    """Return items on the ground at ``(year, x, y)`` with owners filtered out.

    Some call sites expect ``items.list_at`` to return an iterable rather than a
    list, so we normalise the result before applying the ownership filter.
    """

    if items is None or not hasattr(items, "list_at"):
        return ()

    try:
        raw: Iterable[Mapping[str, Any]] = items.list_at(year, x, y)
    except Exception:
        return ()

    items_here = list(raw)

    # Filter for items that explicitly have no owner ID set
    ground_items = [
        item for item in items_here if item.get("owner_iid") is None
    ]

    return ground_items
