"""Helpers for monster emote actions and free emote scheduling."""

from __future__ import annotations

import logging
import random
from typing import Any, Mapping, MutableMapping

from mutants.debug import turnlog

LOG = logging.getLogger(__name__)

__all__ = [
    "EMOTE_LINES",
    "cascade_emote_action",
    "execute_free_emote",
    "schedule_free_emote",
]

EMOTE_LINES: tuple[str, ...] = (
    "{monster} is looking awfully sad.",
    "{monster} is singing a strange song.",
    "{monster} is making strange noises.",
    "{monster} looks at you.",
    "{monster} pleads with you.",
    "{monster} is trying to make friends with you.",
    "{monster} is wondering what you're doing.",
    "{monster} stares into the distance.",
    "{monster} hums a battle hymn.",
    "{monster} sharpens their claws.",
    "{monster} flexes ominously.",
    "{monster} practices a victory pose.",
    "{monster} whispers something unintelligible.",
    "{monster} checks the horizon for danger.",
    "{monster} mutters about the weather.",
    "{monster} pats their pockets for supplies.",
    "{monster} draws a sigil in the dust.",
    "{monster} takes a deep, steadying breath.",
    "{monster} adjusts their helmet.",
    "{monster} bounces on their heels.",
)


def _monster_id(monster: Mapping[str, Any]) -> str:
    ident = monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
    if isinstance(ident, str) and ident:
        return ident
    return "?"


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("name") or monster.get("monster_id")
    if isinstance(name, str) and name:
        return name
    ident = monster.get("id") or monster.get("instance_id")
    if isinstance(ident, str) and ident:
        return ident
    return "The monster"


def _resolve_feedback_bus(ctx: Any) -> Any:
    if isinstance(ctx, Mapping):
        return ctx.get("feedback_bus")
    return getattr(ctx, "feedback_bus", None)


def _resolve_scheduler(ctx: Any) -> Any:
    if isinstance(ctx, Mapping):
        scheduler = ctx.get("turn_scheduler")
    else:
        scheduler = getattr(ctx, "turn_scheduler", None)
    if scheduler is None:
        return None
    queue = getattr(scheduler, "queue_free_emote", None)
    return scheduler if callable(queue) else None


def _emit_emote(
    monster: Mapping[str, Any],
    ctx: Any,
    rng: random.Random,
    *,
    origin: str,
    gate: str,
) -> Mapping[str, Any]:
    if not isinstance(monster, Mapping):
        return {"ok": False, "reason": "invalid_monster"}
    if not EMOTE_LINES:
        return {"ok": False, "reason": "no_lines"}

    try:
        index = int(rng.randrange(len(EMOTE_LINES)))
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to roll emote index")
        index = 0
    index = max(0, min(len(EMOTE_LINES) - 1, index))
    template = EMOTE_LINES[index]
    message = template.format(monster=_monster_display_name(monster))

    bus = _resolve_feedback_bus(ctx)
    if hasattr(bus, "push"):
        try:
            bus.push("COMBAT/INFO", message)
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("Failed to push emote message to feedback bus")

    payload: dict[str, Any] = {
        "ok": True,
        "message": message,
        "index": index,
        "origin": origin,
    }

    try:
        turnlog.emit(
            ctx,
            "AI/ACT/EMOTE",
            monster=_monster_id(monster),
            index=index,
            message=message,
            origin=origin,
            gate=gate,
        )
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to emit emote turnlog entry")

    return payload


def cascade_emote_action(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
    rng: random.Random,
) -> Mapping[str, Any]:
    """Handle the cascade ``EMOTE`` action."""

    return _emit_emote(monster, ctx, rng, origin="cascade", gate="EMOTE")


def execute_free_emote(
    monster: Mapping[str, Any],
    ctx: Any,
    rng: random.Random,
    *,
    gate: str,
) -> None:
    """Emit a free emote line for *monster* using *rng*."""

    _emit_emote(monster, ctx, rng, origin="free", gate=gate)


def schedule_free_emote(
    monster: Mapping[str, Any],
    ctx: Any,
    *,
    gate: str,
) -> None:
    """Queue a free emote event for the active :class:`TurnScheduler`."""

    scheduler = _resolve_scheduler(ctx)
    if scheduler is None:
        return
    try:
        scheduler.queue_free_emote(monster, gate=gate)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to queue free emote")
