from __future__ import annotations

import logging
import random
from enum import Enum
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from mutants.debug import turnlog
from mutants.services.combat_config import CombatConfig

LOG = logging.getLogger(__name__)


class MonsterStatus(Enum):
    """High-level sleep/awake state for a monster instance."""

    AWAKE = "awake"
    ASLEEP = "asleep"

    @classmethod
    def from_value(cls, value: Any) -> "MonsterStatus":
        token = _normalize_status_token(value)
        if token in _ASLEEP_TOKENS:
            return cls.ASLEEP
        if token == cls.AWAKE.value:
            return cls.AWAKE
        return cls.AWAKE


_ASLEEP_TOKENS = {"asleep", "sleep", "sleeping"}

_DEFAULT_WAKE_ON_LOOK = 15
_DEFAULT_WAKE_ON_ENTRY = 10

_WAKE_EVENT_LOOK = "LOOK"
_WAKE_EVENT_ENTRY = "ENTRY"

__all__ = [
    "MonsterStatus",
    "monster_status",
    "should_wake",
    "wake_monster",
]


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


def _normalize_status_token(value: Any) -> str | None:
    if isinstance(value, MonsterStatus):
        return value.value
    if value is None:
        return None
    try:
        token = str(value).strip().lower()
    except Exception:
        return None
    return token or None


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


def _monster_state_payload(monster: Any) -> Any:
    if isinstance(monster, Mapping):
        if "state" in monster:
            return monster.get("state")
    return getattr(monster, "state", None)


def _status_from_state(state: Any) -> MonsterStatus | None:
    if state is None:
        return None
    if isinstance(state, Mapping):
        token = _normalize_status_token(state.get("status"))
        if token in _ASLEEP_TOKENS:
            return MonsterStatus.ASLEEP
        if token == MonsterStatus.AWAKE.value:
            return MonsterStatus.AWAKE
    elif hasattr(state, "status"):
        return MonsterStatus.from_value(getattr(state, "status"))
    return None


def _status_from_container(monster: Any) -> MonsterStatus | None:
    candidates: list[Any] = []
    if isinstance(monster, Mapping):
        candidates.extend([monster.get("status"), monster.get("status_id")])
    else:
        for attr in ("status", "status_id"):
            if hasattr(monster, attr):
                candidates.append(getattr(monster, attr))

    for candidate in candidates:
        token = _normalize_status_token(candidate)
        if token in _ASLEEP_TOKENS:
            return MonsterStatus.ASLEEP
        if token == MonsterStatus.AWAKE.value:
            return MonsterStatus.AWAKE
    return None


def _iter_status_entries(monster: Any) -> Iterable[Mapping[str, Any]]:
    sources: list[Any] = []
    if isinstance(monster, Mapping):
        sources.extend(
            [monster.get("status_effects"), monster.get("timers")]
        )
    else:
        for attr in ("status_effects", "timers"):
            if hasattr(monster, attr):
                sources.append(getattr(monster, attr))

    for payload in sources:
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            for entry in payload:
                if isinstance(entry, Mapping):
                    yield entry


def _status_from_effects(monster: Any) -> MonsterStatus | None:
    for entry in _iter_status_entries(monster):
        token = _normalize_status_token(entry.get("status_id") or entry.get("id"))
        if token in _ASLEEP_TOKENS:
            return MonsterStatus.ASLEEP
    return None


def monster_status(monster: Any) -> MonsterStatus:
    """Return the coarse sleep/awake status for ``monster``."""

    state = _monster_state_payload(monster)
    from_state = _status_from_state(state)
    if from_state is not None:
        return from_state

    direct = _status_from_container(monster)
    if direct is not None:
        return direct

    from_effects = _status_from_effects(monster)
    if from_effects is not None:
        return from_effects

    return MonsterStatus.AWAKE


def _set_status_on_state(state: Any, status: MonsterStatus) -> bool:
    if isinstance(state, MutableMapping):
        state["status"] = status.value
        return True
    if hasattr(state, "status"):
        try:
            setattr(state, "status", status)
        except Exception:
            try:
                setattr(state, "status", status.value)
            except Exception:
                return False
        return True
    return False


def _set_status_on_container(monster: Any, status: MonsterStatus) -> bool:
    updated = False
    state = _monster_state_payload(monster)
    if _set_status_on_state(state, status):
        updated = True

    if isinstance(monster, MutableMapping):
        monster["status"] = status.value
        updated = True
    else:
        for attr in ("status", "status_id"):
            if hasattr(monster, attr):
                try:
                    setattr(monster, attr, status)
                except Exception:
                    try:
                        setattr(monster, attr, status.value)
                    except Exception:
                        continue
                updated = True
                break
    return updated


def _clear_sleep_effects(monster: Any) -> bool:
    changed = False
    if isinstance(monster, MutableMapping):
        for key in ("status_effects", "timers"):
            payload = monster.get(key)
            if isinstance(payload, list):
                filtered = [
                    entry
                    for entry in payload
                    if not _normalize_status_token(entry.get("status_id") or entry.get("id"))
                    in _ASLEEP_TOKENS
                ]
                if len(filtered) != len(payload):
                    monster[key] = filtered
                    changed = True
    else:
        for attr in ("status_effects", "timers"):
            if hasattr(monster, attr):
                payload = getattr(monster, attr)
                if isinstance(payload, list):
                    filtered = [
                        entry
                        for entry in payload
                        if not _normalize_status_token(entry.get("status_id") or entry.get("id"))
                        in _ASLEEP_TOKENS
                    ]
                    if len(filtered) != len(payload):
                        try:
                            setattr(monster, attr, filtered)
                            changed = True
                        except Exception:
                            pass
    return changed


def _ensure_skip_next_action(monster: Any) -> None:
    state = _monster_state_payload(monster)
    if isinstance(state, MutableMapping):
        state["skip_next_action"] = True
    elif hasattr(state, "skip_next_action"):
        try:
            setattr(state, "skip_next_action", True)
        except Exception:
            pass

    if isinstance(monster, MutableMapping):
        ai_state = monster.get("_ai_state")
        if not isinstance(ai_state, MutableMapping):
            ai_state = {}
            monster["_ai_state"] = ai_state
        ai_state["skip_next_action"] = True
    elif hasattr(monster, "ai_state"):
        ai_state = getattr(monster, "ai_state")
        if isinstance(ai_state, MutableMapping):
            ai_state["skip_next_action"] = True
        elif ai_state is None:
            try:
                setattr(monster, "ai_state", {"skip_next_action": True})
            except Exception:
                pass


def _monster_id(monster: Any) -> str:
    if isinstance(monster, Mapping):
        for key in ("id", "instance_id", "monster_id"):
            raw = monster.get(key)
            if raw is None:
                continue
            token = str(raw).strip()
            if token:
                return token
    for key in ("id", "instance_id", "monster_id"):
        raw = getattr(monster, key, None)
        if raw is None:
            continue
        token = str(raw).strip()
        if token:
            return token
    return "?"


def _emit_wake_event(ctx: Any, monster: Any, reason: str | None) -> None:
    monster_id = _monster_id(monster)
    reason_token = (reason or "wake").lower()
    turnlog.emit(ctx, "AI/WAKE", monster=monster_id, reason=reason_token)
    LOG.info("AI/WAKE mon=%s reason=%s", monster_id, reason_token)


def wake_monster(ctx: Any, monster: Any, *, reason: str | None = None) -> bool:
    """Ensure ``monster`` is marked awake and skip its next action."""

    if monster_status(monster) != MonsterStatus.ASLEEP:
        return False

    status_changed = _set_status_on_container(monster, MonsterStatus.AWAKE)
    effects_changed = _clear_sleep_effects(monster)
    _ensure_skip_next_action(monster)
    _emit_wake_event(ctx, monster, reason)
    return status_changed or effects_changed
