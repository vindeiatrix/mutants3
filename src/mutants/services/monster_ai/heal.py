"""Healing helpers for monster AI actions."""

from __future__ import annotations

from typing import Any, Mapping

from mutants.services.combat_config import CombatConfig


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def monster_level(monster: Mapping[str, Any]) -> int:
    """Return the monster level with a floor of ``1``."""

    level = _coerce_int(monster.get("level"), default=1)
    return max(1, level)


def heal_amount(monster: Mapping[str, Any]) -> int:
    """Amount of HP restored by a single heal action."""

    level = monster_level(monster)
    return max(1, level + 5)


def heal_cost(monster: Mapping[str, Any], config: CombatConfig | None = None) -> int:
    """Return the ion cost for a heal action."""

    if isinstance(config, CombatConfig):
        multiplier = config.heal_cost
    else:
        multiplier = CombatConfig().heal_cost
    multiplier = max(1, _coerce_int(multiplier, default=CombatConfig().heal_cost))
    return monster_level(monster) * multiplier


def has_sufficient_ions(monster: Mapping[str, Any], cost: int) -> bool:
    """Return ``True`` when the monster can pay ``cost`` ions."""

    available = _coerce_int(monster.get("ions"), default=0)
    return available >= max(0, cost)


__all__ = [
    "heal_amount",
    "heal_cost",
    "has_sufficient_ions",
    "monster_level",
]
