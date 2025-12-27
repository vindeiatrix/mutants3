"""Helpers for processing player logins into active rooms."""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from mutants.app import get_turn_scheduler
from mutants.services import combat_loot, monster_actions, player_state as pstate
from mutants.services.combat_config import CombatConfig

LOG = logging.getLogger(__name__)

__all__ = ["handle_login_entry"]


class _NullMonsters:
    """Sentinel that reports no monsters during scheduler pass-through."""

    def list_at(self, year: int, x: int, y: int) -> Iterable[Mapping[str, Any]]:  # pragma: no cover - simple
        return []


def _sanitize_ctx(ctx: Any) -> MutableMapping[str, Any]:
    if not isinstance(ctx, MutableMapping):
        raise TypeError("login context must be a mutable mapping")
    return ctx


def _resolve_player_pair(state_hint: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    try:
        state, active = pstate.get_active_pair(state_hint if isinstance(state_hint, Mapping) else None)
    except Exception:
        state, active = pstate.get_active_pair()
    if not isinstance(state, Mapping):
        state = {}
    if not isinstance(active, Mapping):
        active = {}
    return state, active


def _player_pos(state: Mapping[str, Any], active: Mapping[str, Any]) -> Optional[tuple[int, int, int]]:
    try:
        return pstate.canonical_player_pos(state)
    except Exception:
        try:
            return pstate.canonical_player_pos(active)
        except Exception:
            return None


def _pull_monsters(ctx: MutableMapping[str, Any]) -> Any:
    return ctx.get("monsters")


def _advance_scheduler(ctx: MutableMapping[str, Any]) -> bool:
    try:
        scheduler = get_turn_scheduler(ctx)
    except RuntimeError:
        return False

    null_monsters = _NullMonsters()
    original_monsters = ctx.get("monsters")
    ctx["monsters"] = null_monsters
    try:
        advance = getattr(scheduler, "advance_invalid", None)
        if callable(advance):
            advance(token="login-entry", resolved="login-entry")
        else:
            scheduler.tick(lambda: ("login-entry", "login-entry"))  # type: ignore[attr-defined]
        return True
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to advance scheduler during login entry")
        return False
    finally:
        if original_monsters is None:
            ctx.pop("monsters", None)
        else:
            ctx["monsters"] = original_monsters


def _resolve_rng(ctx: Mapping[str, Any], rng: Optional[random.Random]) -> random.Random:
    if isinstance(rng, random.Random):
        return rng
    candidate = ctx.get("monster_ai_rng")
    if isinstance(candidate, random.Random):
        return candidate
    return random.Random()


def _monster_ident(monster: Mapping[str, Any]) -> Optional[str]:
    for key in ("id", "instance_id", "monster_id"):
        value = monster.get(key)
        if value is None:
            continue
        token = str(value).strip()
        if token:
            return token
    return None


def handle_login_entry(
    ctx: Any,
    *,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Resolve monster targeting when a player logs into an occupied room."""

    context = _sanitize_ctx(ctx)
    state_hint = context.get("player_state")
    state, active = _resolve_player_pair(state_hint)
    pos = _player_pos(state, active)
    monsters = _pull_monsters(context)

    if pos is None or monsters is None or not hasattr(monsters, "list_at"):
        return {"ticks": 0, "results": []}

    year, x, y = pos
    try:
        monsters_here = list(monsters.list_at(year, x, y))  # type: ignore[attr-defined]
    except Exception:
        monsters_here = []

    if not monsters_here:
        return {"ticks": 0, "results": []}

    tick_logged = _advance_scheduler(context)
    rng_obj = _resolve_rng(context, rng)

    config = context.get("combat_config")

    bus = context.get("feedback_bus")

    results: list[Dict[str, Any]] = []
    for monster in monsters_here:
        target_monster = monster
        monster_id = _monster_ident(monster)
        if monster_id and hasattr(monsters, "get"):
            try:
                lookup = monsters.get(monster_id)  # type: ignore[attr-defined]
            except Exception:
                lookup = None
            if isinstance(lookup, MutableMapping):
                target_monster = lookup

        outcome = monster_actions.roll_entry_target(
            target_monster,
            state,
            rng_obj,
            config=config if isinstance(config, CombatConfig) else None,
            bus=bus,
            ctx=context,
        )
        results.append(outcome)

        if outcome.get("target_set") and hasattr(monsters, "mark_dirty"):
            try:
                if monster_id and hasattr(monsters, "get"):
                    monsters.get(monster_id)  # type: ignore[attr-defined]
                if hasattr(monsters, "mark_targeting"):
                    monsters.mark_targeting(monster)  # type: ignore[attr-defined]
                monsters.mark_dirty(monster_id)  # type: ignore[attr-defined]
            except Exception:
                LOG.debug("Failed to mark monsters dirty after login target roll", exc_info=True)

    return {"ticks": 1 if tick_logged else 0, "results": results}

