from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from mutants.registries.world import load_nearest_year, list_years
from mutants.services import player_state as pstate
from ..services import item_transfer as itx


def _floor_to_century(year: int) -> int:
    """Return the start of the century for ``year`` (e.g., 2314 -> 2300)."""

    return (int(year) // 100) * 100


def _parse_year(arg: str) -> Optional[int]:
    """Extract the first integer value from ``arg`` if possible."""

    if arg is None:
        return None
    s = arg.strip()
    if not s:
        return None
    sign = 1
    if s[0] in {"+", "-"}:
        if s[0] == "-":
            sign = -1
        s = s[1:]
    digits: list[str] = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if not digits:
        return None
    return sign * int("".join(digits))


def _available_years(ctx: Dict[str, Any]) -> list[int]:
    """Return the available world years, allowing tests to override them."""

    years = ctx.get("world_years")
    if callable(years):  # pragma: no branch - exercised in tests via dummy callable
        try:
            years = years()
        except Exception:
            years = None

    sanitized: list[int] = []
    iterable: Optional[Iterable[Any]]
    if isinstance(years, Iterable) and not isinstance(years, (str, bytes)):
        iterable = years
    else:
        iterable = None

    if iterable is None:
        try:
            iterable = list_years()
        except Exception:
            iterable = []

    for raw in iterable:
        try:
            sanitized.append(int(raw))
        except Exception:
            continue
    return sorted(set(sanitized))


def travel_cmd(arg: str, ctx: Dict[str, Any]) -> None:
    bus = ctx["feedback_bus"]

    year_raw = _parse_year(arg or "")
    if year_raw is None:
        bus.push("SYSTEM/WARN", "Usage: TRAVEL <year>  (e.g., 'tra 2100').")
        return

    target = _floor_to_century(year_raw)
    years = _available_years(ctx)
    if years and target > max(years):
        bus.push("SYSTEM/WARN", "That year doesn't exist yet!")
        return

    loader = ctx.get("world_loader", load_nearest_year)
    try:
        world = loader(target)
    except FileNotFoundError:
        bus.push("SYSTEM/ERROR", "No worlds found in state/world/.")
        return

    resolved_year = int(getattr(world, "year", target))

    player = itx._load_player()
    itx._ensure_inventory(player)
    player["pos"] = [resolved_year, 0, 0]
    itx._save_player(player)

    ctx["player_state"] = pstate.load_state()
    ctx["render_next"] = True
    ctx["peek_vm"] = None
    bus.push("SYSTEM/OK", f"Travel complete. Year: {resolved_year}.")


def register(dispatch, ctx) -> None:
    dispatch.register("travel", lambda arg: travel_cmd(arg, ctx))
