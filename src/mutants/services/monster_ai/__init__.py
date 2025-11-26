from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, Iterable, List, Mapping, Sequence, Tuple

from mutants.services import player_state as pstate
from mutants.debug import turnlog

from mutants.services.combat_config import CombatConfig

from .wake import should_wake
from . import tracking as tracking_mod

if TYPE_CHECKING:  # pragma: no cover - typing aid
    from .. import monster_actions as monster_actions_module


def _monster_actions() -> "monster_actions_module":
    from .. import monster_actions as monster_actions_module

    return monster_actions_module

LOG = logging.getLogger(__name__)

# Default weights for the number of action credits (0..3) a monster may earn on
# a tick. The distribution favours zero or one action while still allowing
# occasional bursts, matching the "sometimes nothing, sometimes bursty" brief.
DEFAULT_CREDIT_WEIGHTS: tuple[float, float, float, float] = (
    0.5,
    0.3,
    0.15,
    0.05,
)

_FALLBACK_COMBAT_CONFIG = CombatConfig()
_WAKE_EVENT_NAMES = ("LOOK", "ENTRY")


def _pull(ctx: Any, key: str) -> Any:
    if isinstance(ctx, Mapping):
        return ctx.get(key)
    return getattr(ctx, key, None)


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        return token or None
    try:
        token = str(value).strip()
    except Exception:
        return None
    return token or None


def _normalize_pos(value: Any) -> tuple[int, int, int] | None:
    coords: Iterable[Any]
    if isinstance(value, Mapping):
        coords = (value.get("year"), value.get("x"), value.get("y"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        coords = value
    else:
        return None

    raw = list(coords)
    if len(raw) != 3:
        return None
    try:
        year, x, y = (int(raw[0]), int(raw[1]), int(raw[2]))
    except (TypeError, ValueError):
        return None
    return year, x, y


def _is_alive(monster: Mapping[str, Any]) -> bool:
    hp_block = monster.get("hp")
    if isinstance(hp_block, Mapping):
        try:
            return int(hp_block.get("current", 0)) > 0
        except (TypeError, ValueError):
            return True
    return True


def _monster_id(monster: Mapping[str, Any]) -> str:
    for key in ("id", "instance_id", "monster_id"):
        mid = _normalize_id(monster.get(key))
        if mid:
            return mid
    return "?"


def _resolve_rng(ctx: Any) -> random.Random:
    candidate = _pull(ctx, "monster_ai_rng")
    if candidate and hasattr(candidate, "random"):
        return candidate  # type: ignore[return-value]
    rng = getattr(_resolve_rng, "_rng", None)
    if not isinstance(rng, random.Random):
        rng = random.Random()
        setattr(_resolve_rng, "_rng", rng)
    return rng


def _sanitize_weights(weights: Any) -> tuple[float, float, float, float] | None:
    if isinstance(weights, Sequence) and not isinstance(weights, (str, bytes)):
        sanitized: list[float] = []
        for value in list(weights)[:4]:
            try:
                weight = float(value)
            except (TypeError, ValueError):
                return None
            sanitized.append(max(0.0, weight))
        while len(sanitized) < 4:
            sanitized.append(0.0)
        if any(sanitized):
            return tuple(sanitized)  # type: ignore[return-value]
    return None


def _resolve_weights(ctx: Any) -> tuple[float, float, float, float]:
    custom = _pull(ctx, "monster_ai_credit_weights")
    sanitized = _sanitize_weights(custom)
    if sanitized is not None:
        return sanitized
    return DEFAULT_CREDIT_WEIGHTS


def _resolve_combat_config(ctx: Any) -> CombatConfig:
    candidate = _pull(ctx, "combat_config")
    if isinstance(candidate, CombatConfig):
        return candidate
    return _FALLBACK_COMBAT_CONFIG


def _extract_event_tokens(raw: str | None) -> List[str]:
    tokens: List[str] = []
    if raw is None:
        return tokens
    cleaned = str(raw).strip().upper()
    if not cleaned:
        return tokens

    def _add(token: str) -> None:
        if token and token not in tokens:
            tokens.append(token)

    _add(cleaned)
    for separator in ("/", " ", "-", ":"):
        if separator in cleaned:
            for part in cleaned.split(separator):
                _add(part)
    return tokens


def _resolve_wake_events(token: str, resolved: str | None) -> Tuple[str, ...]:
    events: List[str] = []
    for raw in (resolved, token):
        for candidate in _extract_event_tokens(raw):
            if candidate in _WAKE_EVENT_NAMES and candidate not in events:
                events.append(candidate)
    return tuple(events)


def _resolve_wake_rng(ctx: Any, fallback: random.Random) -> random.Random:
    candidate = _pull(ctx, "monster_wake_rng")
    if candidate and hasattr(candidate, "random"):
        return candidate  # type: ignore[return-value]
    return fallback


def _roll_credits(rng: Any, weights: Sequence[float]) -> int:
    total = float(sum(weights))
    if total <= 0:
        return 0
    roll = float(getattr(rng, "random")()) * total
    cumulative = 0.0
    for idx, weight in enumerate(weights):
        cumulative += float(weight)
        if roll < cumulative:
            return idx
    return len(weights) - 1


def _log_tick(ctx: Any, monster: Mapping[str, Any], credits: int) -> None:
    mid = _monster_id(monster)
    message = f"mon={mid} credits={credits}"
    turnlog.emit(ctx, "AI/TICK", message=message, mon=mid, credits=credits)
    LOG.info("AI/TICK %s", message)


def _iter_aggro_monsters(monsters: Any, *, year: int, x: int, y: int) -> Iterable[Mapping[str, Any]]:
    if monsters is None:
        return []
    list_at = getattr(monsters, "list_at", None)
    if not callable(list_at):
        return []
    try:
        entries = list_at(year, x, y)
    except Exception:
        return []
    result: list[Mapping[str, Any]] = []
    for entry in entries:
        if isinstance(entry, Mapping):
            result.append(entry)
    return result


def _iter_targeted_monsters(
    monsters: Any, *, year: int, player_id: str
) -> Iterable[Mapping[str, Any]]:
    if monsters is None:
        return []
    list_all = getattr(monsters, "list_all", None)
    if not callable(list_all):
        return []
    try:
        entries = list_all()
    except Exception:
        return []

    result: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        target = _normalize_id(entry.get("target_player_id"))
        if target != player_id:
            continue
        pos = _normalize_pos(entry.get("pos"))
        if pos is None or int(pos[0]) != int(year):
            continue
        result.append(entry)
    return result


def on_player_command(ctx: Any, *, token: str, resolved: str | None) -> None:
    """Advance monster turns after a player command."""

    monsters = _pull(ctx, "monsters")
    if monsters is None:
        return

    player_state = _pull(ctx, "player_state")
    if isinstance(player_state, Mapping):
        try:
            state, active = pstate.get_active_pair(player_state)
        except Exception:
            state, active = pstate.get_active_pair()
    else:
        state, active = pstate.get_active_pair()

    player_id = _normalize_id(active.get("id") if isinstance(active, Mapping) else None)
    if not player_id:
        player_id = _normalize_id(state.get("active_id") if isinstance(state, Mapping) else None)
    if not player_id:
        return

    source_state: Mapping[str, Any] | None = None
    if isinstance(state, Mapping):
        source_state = state
    elif isinstance(active, Mapping):
        source_state = active
    if source_state is None:
        return
    try:
        year, x, y = pstate.canonical_player_pos(source_state)
    except Exception:
        return

    rng = _resolve_rng(ctx)
    weights = _resolve_weights(ctx)
    config = _resolve_combat_config(ctx)
    wake_rng = _resolve_wake_rng(ctx, rng)
    wake_events = _resolve_wake_events(token, resolved)
    actions_mod = _monster_actions()

    bus = _pull(ctx, "feedback_bus")
    mark_dirty = getattr(monsters, "mark_dirty", None)

    pos = (year, x, y)
    reentry_ids = tracking_mod.update_target_positions(monsters, player_id, pos)

    processed: set[str] = set()

    def _process_monster(monster: Mapping[str, Any], *, allow_target_roll: bool, require_wake: bool) -> None:
        target = _normalize_id(monster.get("target_player_id"))
        if target not in (player_id, None):
            return
        if not _is_alive(monster):
            return
        mon_pos = _normalize_pos(monster.get("pos"))
        if mon_pos is None:
            return
        if int(mon_pos[0]) != int(year):
            return

        monster_id = _monster_id(monster)
        processed.add(monster_id)

        if allow_target_roll and target is None:
            outcome = actions_mod.roll_entry_target(
                monster,
                source_state,
                rng,
                config=config,
                bus=bus,
            )
            if callable(mark_dirty) and outcome.get("target_set"):
                try:
                    mark_dirty()
                except Exception:  # pragma: no cover - best effort
                    pass
            if _normalize_id(monster.get("target_player_id")) != player_id:
                return

        if require_wake and wake_events:
            woke = False
            for event_name in wake_events:
                if should_wake(monster, event_name, wake_rng, config):
                    woke = True
                    break
            if not woke:
                return

        reentry = monster_id in reentry_ids
        separated_from_player = mon_pos != pos
        credits = _roll_credits(rng, weights)
        if separated_from_player and target == player_id and credits <= 0:
            credits = 1
        if reentry and credits <= 0:
            credits = 1
            turnlog.emit(
                ctx,
                "AI/REENTRY",
                monster=monster_id,
                player=player_id,
            )
        _log_tick(ctx, monster, credits)
        if credits <= 0:
            return

        for _ in range(credits):
            try:
                actions_mod.execute_random_action(monster, ctx, rng=rng)
            except Exception:  # pragma: no cover - defensive
                LOG.exception("Monster action execution failed", extra={"monster": _monster_id(monster)})
                break

    for monster in _iter_targeted_monsters(monsters, year=year, player_id=player_id):
        _process_monster(monster, allow_target_roll=False, require_wake=False)

    for monster in _iter_aggro_monsters(monsters, year=year, x=x, y=y):
        monster_id = _monster_id(monster)
        if monster_id in processed:
            continue
        if _normalize_pos(monster.get("pos")) != pos:
            continue
        _process_monster(monster, allow_target_roll=True, require_wake=True)

