from __future__ import annotations

"""Time travel command that repositions the active player."""

from typing import Any, Callable, Dict


def _parse_year(arg: str) -> int | None:
    """Parse a year argument, returning ``None`` when invalid."""

    s = (arg or "").strip()
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def travel_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    """Handle the ``travel`` command."""

    bus = ctx["feedback_bus"]
    state_manager = ctx.get("state_manager")
    if state_manager is None:
        bus.push("SYSTEM/WARN", "Travel unavailable.")
        return

    year = _parse_year(arg)
    if year is None:
        bus.push("SYSTEM/WARN", "Usage: travel <year>")
        return

    loader: Callable[[int], Any] | None = ctx.get("world_loader")
    if callable(loader):
        try:
            loader(int(year))
        except Exception:
            bus.push(
                "SYSTEM/WARN",
                f"World {year} unavailable; a fallback may be used.",
            )

    state_manager.set_position(int(year), 0, 0)
    bus.push("SYSTEM/OK", f"Traveled to Year {year}; position set to (0, 0).")


def register(dispatch, ctx) -> None:
    dispatch.register("travel", lambda arg: travel_cmd(arg, ctx))
