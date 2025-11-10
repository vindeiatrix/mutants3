"""Monster progression triggered by combat kill events."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, TYPE_CHECKING

from .monsters_state import MonstersState

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from mutants.ui.feedback import FeedbackBus


KILL_EVENT_KIND = "COMBAT/KILL"


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _handle_kill_event(state: MonstersState, event: Mapping[str, Any]) -> None:
    if event.get("kind") != KILL_EVENT_KIND:
        return

    monster_id = _as_str(event.get("killer_id"))
    if not monster_id:
        return

    if not state.level_up_monster(monster_id):
        return

    try:
        state.save()
    except Exception:
        # Persistence issues should not break the game loop; ignore failures.
        pass


def attach(bus: "FeedbackBus", state: MonstersState) -> None:
    """Attach kill-based leveling to the provided feedback ``bus``."""

    def _listener(event: MutableMapping[str, Any]) -> None:
        _handle_kill_event(state, event)

    bus.subscribe(_listener)


# EXP formula (can be adjusted later in one place)
def exp_for(level: int, exp_bonus: int = 0) -> int:
    return max(0, 100 * int(level) + int(exp_bonus))
