from __future__ import annotations

from typing import Any, Tuple

from mutants.registries.world import load_year, save_all as save_worlds
from mutants.services import player_state as pstate
from mutants.registries import items_instances as itemsreg


def _clamp_to_bounds(year: int, x: int, y: int) -> Tuple[int, int]:
    """Clamp (x, y) to the bounds of the target year's world."""
    world = load_year(int(year))  # ensures the world is loaded/cached
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

    # 2) Mutate the active player's year while clamping coordinates.
    def _mutator(state, active):
        pos = list(active.get("pos") or [2000, 0, 0])
        year = int(pos[0] or 2000)
        x = int(pos[1] or 0)
        y = int(pos[2] or 0)
        nx, ny = _clamp_to_bounds(target_year, x, y)
        active["pos"] = [int(target_year), nx, ny]

    new_state = pstate.mutate_active(_mutator)

    # 3) Reset items cache so ground loot reflects the new year.
    try:
        itemsreg._CACHE = None  # type: ignore[attr-defined]
    except Exception:
        pass

    # 4) Refresh runtime context and prompt a re-render.
    ctx["player_state"] = new_state
    ctx["peek_vm"] = None
    ctx["render_next"] = True
    ctx["feedback_bus"].push("SYSTEM/OK", f"Time shift complete. Year: {target_year}.")


def do_time(arg: str, ctx: dict[str, Any]) -> None:
    query = (arg or "").strip()
    if not query:
        ctx["feedback_bus"].push("SYSTEM/OK", "Usage: time <2000|2100>")
        return
    try:
        year = int(query)
    except ValueError:
        ctx["feedback_bus"].push("SYSTEM/ERROR", "Year must be numeric (e.g., 2000 or 2100).")
        return
    if year not in (2000, 2100):
        ctx["feedback_bus"].push("SYSTEM/ERROR", "Currently, you can switch to 2000 or 2100.")
        return
    _switch_year(ctx, year)


def register(dispatch, ctx) -> None:
    dispatch.register("time", lambda arg: do_time(arg, ctx))
