"""Feedback helpers for monster taunt events."""

from __future__ import annotations

import logging
import random
from typing import Any, Mapping

LOG = logging.getLogger(__name__)

__all__ = ["emit_taunt"]

_READY_CHANCE = 5
_READY_TEMPLATE = "{monster} is getting ready to combat you!"


def _monster_display_name(monster: Mapping[str, Any]) -> str:
    name = monster.get("name") or monster.get("monster_id")
    if isinstance(name, str) and name:
        return name
    ident = monster.get("id") or monster.get("instance_id")
    if isinstance(ident, str) and ident:
        return ident
    return "The monster"


def _should_emit_ready(rng: random.Random) -> bool:
    try:
        roll = int(rng.randrange(100))
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to roll monster ready message chance")
        return False
    return 0 <= roll < _READY_CHANCE


def emit_taunt(
    monster: Mapping[str, Any] | None,
    bus: Any,
    rng: random.Random,
) -> dict[str, Any]:
    """Emit the monster taunt message to *bus*.

    Returns a payload describing the emitted messages. The payload always
    contains the keys ``ok`` and ``ready``. ``ready`` indicates whether the
    follow-up readiness line was emitted.
    """

    if not isinstance(monster, Mapping):
        return {"ok": False, "message": None, "ready": False, "ready_message": None}

    taunt_raw = monster.get("taunt")
    taunt = taunt_raw.strip() if isinstance(taunt_raw, str) else None
    if not taunt:
        return {"ok": True, "message": None, "ready": False, "ready_message": None}

    ready_message: str | None = None
    ready = False

    if hasattr(bus, "push"):
        try:
            bus.push("COMBAT/TAUNT", taunt)
            if hasattr(bus, "messages"):
                try:
                    kind, message, meta = bus.messages[-1]
                except (AttributeError, IndexError, ValueError):
                    pass
                else:
                    if kind == "COMBAT/TAUNT" and not meta:
                        bus.messages[-1] = (kind, message)
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("Failed to push monster taunt message")

    if _should_emit_ready(rng):
        ready = True
        ready_message = _READY_TEMPLATE.format(monster=_monster_display_name(monster))
        if hasattr(bus, "push"):
            try:
                bus.push("COMBAT/READY", ready_message)
            except Exception:  # pragma: no cover - defensive guard
                LOG.exception("Failed to push monster readiness message")

    return {
        "ok": True,
        "message": taunt,
        "ready": ready,
        "ready_message": ready_message,
    }
