"""In-memory data structures for live player state and saves."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
import copy


@dataclass(frozen=True)
class PlayerTemplate:
    """Immutable baseline for a class."""

    class_id: str
    data: Dict[str, Any]


@dataclass
class PlayerState:
    """Mutable live state for a player."""

    data: Dict[str, Any] = field(default_factory=dict)

    def clamp(self) -> None:
        """Clamp obviously invalid numeric values (hp, stats, money)."""

        hp = self.data.get("hp")
        if isinstance(hp, dict):
            current = hp.get("current")
            maximum = hp.get("max")
            try:
                maximum_int = max(0, int(maximum))
            except (TypeError, ValueError):
                maximum_int = 0
            try:
                current_int = max(0, int(current))
            except (TypeError, ValueError):
                current_int = 0
            if maximum_int and current_int > maximum_int:
                current_int = maximum_int
            hp["max"] = maximum_int
            hp["current"] = current_int

        for field_name in ("level", "exp_points", "exp", "exhaustion"):
            if field_name in self.data:
                try:
                    self.data[field_name] = int(self.data[field_name])
                except (TypeError, ValueError):
                    self.data[field_name] = 0

        for money_key in ("ions", "riblets"):
            if money_key in self.data:
                try:
                    self.data[money_key] = max(0, int(self.data[money_key]))
                except (TypeError, ValueError):
                    self.data[money_key] = 0

    def to_dict(self) -> Dict[str, Any]:
        return self.data


@dataclass
class SaveData:
    meta: Dict[str, Any]
    players: Dict[str, PlayerState]
    active_id: str


def deep_copy_from_template(template: PlayerTemplate) -> PlayerState:
    """Return a deep copy of *template* as a mutable ``PlayerState``."""

    return PlayerState(copy.deepcopy(template.data))

