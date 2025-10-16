from __future__ import annotations

import random
from typing import Any, Mapping

from mutants.services.combat_config import CombatConfig

_DEFAULT_WAKE_ON_LOOK = 15
_DEFAULT_WAKE_ON_ENTRY = 10

_WAKE_EVENT_LOOK = "LOOK"
_WAKE_EVENT_ENTRY = "ENTRY"


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_threshold(value: int) -> int:
    return max(0, min(100, value))


def _normalize_event(event: str | None) -> str | None:
    if event is None:
        return None
    token = str(event).strip().upper()
    if token in (_WAKE_EVENT_LOOK, _WAKE_EVENT_ENTRY):
        return token
    return None


def _threshold_from_config(config: CombatConfig | None, event: str) -> int:
    if isinstance(config, CombatConfig):
        if event == _WAKE_EVENT_LOOK:
            default = config.wake_on_look
        else:
            default = config.wake_on_entry
        coerced = _coerce_int(default)
        if coerced is not None:
            return _clamp_threshold(coerced)
    if event == _WAKE_EVENT_LOOK:
        return _DEFAULT_WAKE_ON_LOOK
    return _DEFAULT_WAKE_ON_ENTRY


def _threshold_from_monster(monster: Mapping[str, Any] | None, event: str) -> int | None:
    if not isinstance(monster, Mapping):
        return None
    key = "wake_on_look" if event == _WAKE_EVENT_LOOK else "wake_on_entry"
    value = _coerce_int(monster.get(key))
    if value is None:
        return None
    return _clamp_threshold(value)


def _roll_percentage(rng: Any) -> int:
    if hasattr(rng, "randrange"):
        try:
            return int(rng.randrange(100))
        except Exception:  # pragma: no cover - defensive guard
            pass
    if hasattr(rng, "random"):
        try:
            return int(float(rng.random()) * 100)
        except Exception:  # pragma: no cover - defensive guard
            pass
    return random.randrange(100)


def should_wake(
    monster: Mapping[str, Any] | None,
    event: str,
    rng: Any,
    config: CombatConfig | None,
) -> bool:
    """Return ``True`` when *monster* should wake for *event*."""

    normalized = _normalize_event(event)
    if normalized is None:
        return True

    override = _threshold_from_monster(monster, normalized)
    threshold = override if override is not None else _threshold_from_config(config, normalized)
    threshold = _clamp_threshold(threshold)
    if threshold <= 0:
        return False
    if threshold >= 100:
        return True

    roll = _roll_percentage(rng)
    return roll < threshold
