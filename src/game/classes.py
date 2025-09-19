"""Concrete character classes with independent state."""

from dataclasses import dataclass, field
from typing import Dict, List

__all__ = ["Thief", "Priest", "Wizard", "Warrior", "Mage"]

BaseStats = Dict[str, int]


@dataclass
class Thief:
    """Sneaky damage dealer."""

    name: str
    class_name: str = "Thief"
    riblets: List[str] = field(default_factory=list)
    ions: Dict[str, int] = field(default_factory=dict)
    experience: int = 0
    stats: BaseStats = field(default_factory=lambda: {"agi": 8, "str": 4, "int": 4})
    inventory: List[str] = field(default_factory=list)

    def add_xp(self, amount: int) -> None:
        self.experience += amount

    def add_item(self, item: str) -> None:
        self.inventory.append(item)


@dataclass
class Priest:
    """Support character with healing prowess."""

    name: str
    class_name: str = "Priest"
    riblets: List[str] = field(default_factory=list)
    ions: Dict[str, int] = field(default_factory=dict)
    experience: int = 0
    stats: BaseStats = field(default_factory=lambda: {"agi": 3, "str": 3, "int": 9})
    inventory: List[str] = field(default_factory=list)

    def add_xp(self, amount: int) -> None:
        self.experience += amount

    def add_item(self, item: str) -> None:
        self.inventory.append(item)


@dataclass
class Wizard:
    """Spell-focused ranged damage dealer."""

    name: str
    class_name: str = "Wizard"
    riblets: List[str] = field(default_factory=list)
    ions: Dict[str, int] = field(default_factory=dict)
    experience: int = 0
    stats: BaseStats = field(default_factory=lambda: {"agi": 4, "str": 2, "int": 10})
    inventory: List[str] = field(default_factory=list)

    def add_xp(self, amount: int) -> None:
        self.experience += amount

    def add_item(self, item: str) -> None:
        self.inventory.append(item)


@dataclass
class Warrior:
    """Front-line melee fighter."""

    name: str
    class_name: str = "Warrior"
    riblets: List[str] = field(default_factory=list)
    ions: Dict[str, int] = field(default_factory=dict)
    experience: int = 0
    stats: BaseStats = field(default_factory=lambda: {"agi": 5, "str": 9, "int": 2})
    inventory: List[str] = field(default_factory=list)

    def add_xp(self, amount: int) -> None:
        self.experience += amount

    def add_item(self, item: str) -> None:
        self.inventory.append(item)


@dataclass
class Mage:
    """Hybrid caster blending offense and utility."""

    name: str
    class_name: str = "Mage"
    riblets: List[str] = field(default_factory=list)
    ions: Dict[str, int] = field(default_factory=dict)
    experience: int = 0
    stats: BaseStats = field(default_factory=lambda: {"agi": 5, "str": 3, "int": 9})
    inventory: List[str] = field(default_factory=list)

    def add_xp(self, amount: int) -> None:
        self.experience += amount

    def add_item(self, item: str) -> None:
        self.inventory.append(item)
