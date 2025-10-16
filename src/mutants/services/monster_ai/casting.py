"""Spell casting helpers for monster AI actions."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from mutants.services.combat_config import CombatConfig


@dataclass(slots=True)
class CastResult:
    """Outcome of a monster spell cast attempt."""

    success: bool
    cost: int
    remaining_ions: int
    roll: Optional[int]
    threshold: Optional[int]
    effect: Optional[str] = None
    reason: Optional[str] = None


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_config(ctx: Any) -> CombatConfig:
    if isinstance(ctx, Mapping):
        candidate = ctx.get("combat_config")
    else:
        candidate = getattr(ctx, "combat_config", None)
    if isinstance(candidate, CombatConfig):
        return candidate
    return CombatConfig()


def _resolve_rng(ctx: Any) -> random.Random:
    if isinstance(ctx, Mapping):
        candidate = ctx.get("monster_ai_rng")
    else:
        candidate = getattr(ctx, "monster_ai_rng", None)
    if isinstance(candidate, random.Random):
        return candidate
    if candidate is not None and hasattr(candidate, "randrange"):
        return candidate  # type: ignore[return-value]
    rng = getattr(_resolve_rng, "_fallback", None)
    if not isinstance(rng, random.Random):
        rng = random.Random()
        setattr(_resolve_rng, "_fallback", rng)
    return rng


def _ai_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    payload = monster.get("_ai_state")
    if isinstance(payload, MutableMapping):
        return payload
    payload = {}
    monster["_ai_state"] = payload
    return payload


def _ledger_state(monster: MutableMapping[str, Any]) -> MutableMapping[str, int]:
    state = _ai_state(monster)
    ledger_raw = state.get("ledger")
    if isinstance(ledger_raw, MutableMapping):
        ledger = ledger_raw
    elif isinstance(ledger_raw, Mapping):
        ledger = dict(ledger_raw)
        state["ledger"] = ledger
    else:
        ledger = {}
        state["ledger"] = ledger

    ions = _coerce_int(ledger.get("ions"), monster.get("ions", 0))
    ions = max(0, ions)
    ledger["ions"] = ions
    monster["ions"] = ions
    return ledger


def try_cast(
    monster: MutableMapping[str, Any],
    ctx: MutableMapping[str, Any],
) -> CastResult:
    """Attempt to cast a monster spell and update the ion ledger."""

    if not isinstance(monster, MutableMapping):
        return CastResult(
            success=False,
            cost=0,
            remaining_ions=0,
            roll=None,
            threshold=None,
            reason="invalid_monster",
        )

    config = _resolve_config(ctx)
    ledger = _ledger_state(monster)
    rng = _resolve_rng(ctx)

    spell_cost = max(0, _coerce_int(config.spell_cost, 0))
    success_threshold = max(0, min(100, _coerce_int(config.spell_success_pct, 0)))

    available_ions = max(0, _coerce_int(ledger.get("ions"), monster.get("ions", 0)))
    ledger["ions"] = available_ions
    monster["ions"] = available_ions

    if available_ions < spell_cost:
        return CastResult(
            success=False,
            cost=0,
            remaining_ions=available_ions,
            roll=None,
            threshold=success_threshold,
            reason="insufficient_ions",
        )

    roll = int(rng.randrange(100)) if success_threshold > 0 else None
    success = False
    if roll is None:
        success = success_threshold >= 100 and spell_cost == 0
    else:
        success = roll < success_threshold

    failure_reason: Optional[str]
    if success:
        cost_paid = spell_cost
        effect = "arcane-burst"
        failure_reason = None
    else:
        cost_paid = spell_cost // 2
        effect = None
        failure_reason = "failed_roll" if roll is not None else "no_chance"

    cost_paid = max(0, min(cost_paid, available_ions))

    remaining = max(0, available_ions - cost_paid)
    ledger["ions"] = remaining
    monster["ions"] = remaining

    return CastResult(
        success=success,
        cost=cost_paid,
        remaining_ions=remaining,
        roll=roll,
        threshold=success_threshold,
        effect=effect,
        reason=failure_reason,
    )


__all__ = ["CastResult", "try_cast"]
