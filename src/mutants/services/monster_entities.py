"""Data models for monster templates and instances."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

DEFAULT_INNATE_ATTACK_LINE = "The {monster} uses {attack}!"


def _sanitize_line(value: Any) -> str:
    if isinstance(value, str):
        token = value.strip()
        if token:
            return token
    return ""


@dataclass(frozen=True)
class MonsterTemplate:
    """Immutable representation of a catalog monster template."""

    monster_id: str
    name: str
    level: int
    hp_max: int
    armour_class: int
    spawn_years: Sequence[int]
    spawnable: bool
    taunt: str
    stats: Mapping[str, Any]
    innate_attack: Mapping[str, Any]
    exp_bonus: Optional[int]
    ions_min: Optional[int]
    ions_max: Optional[int]
    riblets_min: Optional[int]
    riblets_max: Optional[int]
    spells: Sequence[str]
    starter_armour: Sequence[str]
    starter_items: Sequence[str]

    @property
    def innate_attack_line(self) -> str:
        """Return the template's innate attack line template."""

        if isinstance(self.innate_attack, Mapping):
            line = _sanitize_line(self.innate_attack.get("line"))
            if line:
                return line
        return DEFAULT_INNATE_ATTACK_LINE


@dataclass
class MonsterInstance:
    """Light-weight runtime monster instance."""

    instance_id: str
    monster_id: str
    name: str
    innate_attack: Mapping[str, Any]
    template: Optional[MonsterTemplate] = None

    @property
    def innate_attack_line(self) -> str:
        """Return the innate attack line template for the instance."""

        if isinstance(self.innate_attack, Mapping):
            line = _sanitize_line(self.innate_attack.get("line"))
            if line:
                return line
        if self.template is not None:
            return self.template.innate_attack_line
        return DEFAULT_INNATE_ATTACK_LINE
