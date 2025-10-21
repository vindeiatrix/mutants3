from __future__ import annotations

from typing import Any, MutableMapping, Optional

from .context import build_context, current_context
from mutants.engine import session as session_state
from mutants.services.turn_scheduler import TurnScheduler

__all__ = [
    "build_context",
    "current_context",
    "get_turn_scheduler",
    "advance_invalid_turn",
]


def get_turn_scheduler(ctx: Any | None = None) -> TurnScheduler:
    """Return the process-wide :class:`TurnScheduler` instance.

    If no scheduler has been registered yet, one is created using *ctx* or the
    current application context.
    """

    scheduler = session_state.get_turn_scheduler()
    if scheduler is not None:
        return scheduler

    context = ctx if ctx is not None else current_context()
    if context is None:
        raise RuntimeError("Turn scheduler requires an application context")

    scheduler = TurnScheduler(context)
    if isinstance(context, MutableMapping):
        context["turn_scheduler"] = scheduler
    session_state.set_turn_scheduler(scheduler)
    return scheduler


def advance_invalid_turn(
    token: str | None = None,
    *,
    ctx: Any | None = None,
    resolved: Optional[str] = None,
) -> bool:
    """Advance the global scheduler for an invalid command token.

    Returns ``True`` if a scheduler handled the advancement.
    """

    try:
        scheduler = get_turn_scheduler(ctx)
    except RuntimeError:
        return False

    advance = getattr(scheduler, "advance_invalid", None)
    if callable(advance):
        advance(token=token, resolved=resolved)
    else:
        # Fallback for unexpected scheduler implementations.
        raw_token = "" if token is None else str(token)

        def _noop_action() -> tuple[str, Optional[str]]:
            return raw_token, resolved

        scheduler.tick(_noop_action)

    return True
