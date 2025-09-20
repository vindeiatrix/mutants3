from __future__ import annotations

from mutants.services import player_state as pstate


def dex_bonus_for_active(state) -> int:
    """Return the derived dexterity bonus for the active character."""

    stats = pstate.get_stats_for_active(state)
    dex = stats.get("dex", 0)
    try:
        dex_value = int(dex)
    except (TypeError, ValueError):
        dex_value = 0
    return max(0, dex_value // 10)


def armour_class_for_active(state) -> int:
    """Return the active character's armour class."""

    return dex_bonus_for_active(state)
