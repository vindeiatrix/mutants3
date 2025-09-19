"""Protocol definitions for game characters."""

from typing import Dict, List, Protocol


class Character(Protocol):
    """Protocol describing a playable character."""

    name: str
    class_name: str
    riblets: List[str]
    ions: Dict[str, int]
    experience: int
    stats: Dict[str, int]
    inventory: List[str]

    def add_xp(self, amount: int) -> None:
        """Add experience points to the character."""

    def add_item(self, item: str) -> None:
        """Add an item to the character's inventory."""
