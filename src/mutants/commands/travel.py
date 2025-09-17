from __future__ import annotations

import os
import random
import re
from typing import Any, Dict, List

from mutants.services import player_state as pstate


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for player in state.get("players", []):
        if player.get("id") == aid:
            return player
    return (state.get("players") or [{}])[0]


def _floor_century(year: int) -> int:
    return (int(year) // 100) * 100


def _century_label(year: int) -> str:
    # Match existing UI tone (e.g., "21th Century!")
    return f"{(int(year) // 100) + 1}th Century!"


_YEAR_RE = re.compile(r"^(\d{1,6})\.json$", re.I)


def _installed_years() -> List[int]:
    """Return all installed century years discovered on the filesystem."""

    world_dir = os.path.join(os.getcwd(), "state", "world")
    years: List[int] = []
    try:
        for filename in os.listdir(world_dir):
            match = _YEAR_RE.match(filename)
            if not match:
                continue
            year = int(match.group(1))
            if year % 100 == 0:  # centuries only
                years.append(year)
    except FileNotFoundError:
        pass
    return sorted(set(years))


def _year_installed(year: int) -> bool:
    return year in _installed_years()


def _cost_for_trip(cur_year: int, target_year: int) -> int:
    """
    Cost is 3,000 ions per *century* moved.
    Both years are already floored to centuries.
    """

    delta_centuries = abs(int(target_year) - int(cur_year)) // 100
    return 3000 * delta_centuries


def travel_cmd(arg: str, ctx) -> None:
    bus = ctx["feedback_bus"]
    tokens = (arg or "").strip().split()
    if not tokens:
        bus.push("SYSTEM/ERROR", "Usage: TRAVEL [year]")
        return
    # parse and round down to the lower century
    try:
        raw_year = int(tokens[0])
    except ValueError:
        bus.push("SYSTEM/ERROR", "Year must be an integer (e.g., 2100).")
        return
    target_year = _floor_century(raw_year)

    # Check availability (filesystem-driven; future-proof)
    if not _year_installed(target_year):
        bus.push("SYSTEM/ERROR", "That year doesn't exist yet.")
        return

    # Get active player and current year
    state = pstate.load_state()
    player = _active(state)
    pos = player.get("pos") or [2000, 0, 0]
    cur_year = int(pos[0]) if isinstance(pos, (list, tuple)) and len(pos) >= 1 else 2000
    ions = int(player.get("ions", 0) or 0)

    # Same-year travel is free and allowed even with < 3000 ions
    if target_year == cur_year:
        bus.push("SYSTEM/OK", f"You're already in the {_century_label(cur_year)}")
        return

    # Compute cost for a normal trip (3k per century)
    cost = _cost_for_trip(cur_year, target_year)

    # Not enough to even create a portal
    if ions < 3000:
        bus.push("SYSTEM/OK", "You don't have enough ions to create a portal.")
        return

    if ions >= cost:
        # Full travel succeeds
        def _apply(_, active):
            active["ions"] = ions - cost
            active["pos"] = [int(target_year), 0, 0]

        pstate.mutate_active(_apply)
        # Keep the REPL context in sync with disk so x,y are 0,0 immediately.
        ctx["player_state"] = pstate.load_state()
        ctx["render_next"] = False  # traveling does not render a tile
        bus.push("SYSTEM/OK", f"ZAAAPPPP!! You've been sent to the year {target_year} A.D.")
        return

    # Partial travel: choose randomly among installed decades 2000..3000 only
    pool = [year for year in _installed_years() if 2000 <= year <= 3000]
    if not pool:
        # Extremely unlikely (we usually have at least 2000); fail safely
        bus.push("SYSTEM/ERROR", "The portal destabilizes—no safe century anchors available.")
        return
    rnd_year = random.choice(pool)

    def _apply_partial(_, active):
        active["ions"] = 0
        active["pos"] = [int(rnd_year), 0, 0]

    pstate.mutate_active(_apply_partial)
    ctx["player_state"] = pstate.load_state()
    ctx["render_next"] = False
    bus.push("SYSTEM/OK", "ZAAAPPPP!!!! You suddenly feel something has gone terribly wrong!")


def register(dispatch, ctx) -> None:
    dispatch.register("travel", lambda arg: travel_cmd(arg, ctx))
    for alias in ["tra", "trav", "trave"]:
        dispatch.alias(alias, "travel")
