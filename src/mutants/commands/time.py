from __future__ import annotations

from typing import Any, Optional, Tuple

from mutants.registries.world import (
    load_nearest_year,
    list_years,
    save_all as save_worlds,
)
from mutants.services import player_state as pstate
from mutants.registries import items_instances as itemsreg


def _clamp_to_bounds(world: Any, x: int, y: int) -> Tuple[int, int]:
    """Clamp ``(x, y)`` to the bounds of ``world``."""
    min_x, max_x, min_y, max_y = world.bounds
    nx = min(max(x, min_x), max_x)
    ny = min(max(y, min_y), max_y)
    return nx, ny


def _switch_year(ctx: dict[str, Any], target_year: int) -> None:
    # 1) Persist any dirty world changes so edits aren't lost across shifts.
    try:
        save_worlds()
    except Exception:
        # Non-fatal; continue even if save fails (e.g., no dirty state).
        pass

    # 2) Resolve the target world before mutating player state.
    try:
        world = load_nearest_year(int(target_year))
    except FileNotFoundError:
        ctx["feedback_bus"].push("SYSTEM/ERROR", "No worlds found in state/world/.")
        return

    resolved_year = int(getattr(world, "year", int(target_year)))

    def _mutator(state, active):
        pos = list(active.get("pos") or [2000, 0, 0])
        x = int(pos[1] or 0)
        y = int(pos[2] or 0)
        nx, ny = _clamp_to_bounds(world, x, y)
        active["pos"] = [resolved_year, nx, ny]

    new_state = pstate.mutate_active(_mutator)

    # 3) Reset items cache so ground loot reflects the new year.
    _invalidate_items_cache_safely()

    # 4) Refresh runtime context and prompt a re-render.
    ctx["player_state"] = new_state
    ctx["peek_vm"] = None
    ctx["render_next"] = True
    try:
        current_year = int(new_state["active"]["pos"][0])
    except Exception:
        current_year = resolved_year
    ctx["feedback_bus"].push("SYSTEM/OK", f"Time shift complete. Year: {current_year}.")


def _invalidate_items_cache_safely() -> None:
    """Best-effort invalidation of the items-instances read cache."""
    try:
        invalidate = getattr(itemsreg, "invalidate_cache", None)
        if callable(invalidate):
            invalidate()
            return
    except Exception:
        pass
    try:
        itemsreg._CACHE = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _active_year(ctx: dict[str, Any]) -> Optional[int]:
    try:
        return int(ctx["player_state"]["active"]["pos"][0])
    except Exception:
        return None


def _format_years_line(active_year: Optional[int]) -> str:
    years = list_years()
    if not years:
        return "No worlds found in state/world/."
    parts = [f"[{y}]" if active_year == y else str(y) for y in years]
    return "Available years: " + ", ".join(parts)


def do_time(arg: str, ctx: dict[str, Any]) -> None:
    query = (arg or "").strip().lower()
    active_year = _active_year(ctx)

    if not query or query == "help":
        ctx["feedback_bus"].push("SYSTEM/OK", "Usage: time <YEAR>|list|next|prev")
        ctx["feedback_bus"].push("SYSTEM/OK", _format_years_line(active_year))
        return

    if query == "list":
        ctx["feedback_bus"].push("SYSTEM/OK", _format_years_line(active_year))
        return

    years = list_years()
    if not years:
        ctx["feedback_bus"].push("SYSTEM/ERROR", "No worlds found in state/world/.")
        return

    if query in {"next", "prev"}:
        if active_year is None:
            ctx["feedback_bus"].push("SYSTEM/ERROR", "No active year; try: time <YEAR>.")
            return
        target_idx = _index_for_adjacent_year(active_year, years, query == "next")
        _switch_year(ctx, years[target_idx])
        return

    try:
        requested_year = int(query)
    except ValueError:
        ctx["feedback_bus"].push(
            "SYSTEM/ERROR",
            "Year must be numeric or one of: list, next, prev.",
        )
        return

    _switch_year(ctx, requested_year)


def _index_for_adjacent_year(current: int, years: list[int], forward: bool) -> int:
    """Return the index of the next/previous year relative to ``current``."""
    try:
        world = load_nearest_year(current)
        resolved = int(getattr(world, "year", current))
    except Exception:
        resolved = current

    if resolved not in years:
        resolved = min(years, key=lambda y: (abs(y - int(current)), y))

    idx = years.index(resolved)
    if forward:
        return min(idx + 1, len(years) - 1)
    return max(idx - 1, 0)


def register(dispatch, ctx) -> None:
    dispatch.register("time", lambda arg: do_time(arg, ctx))
