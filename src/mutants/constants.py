"""
Shared constants for the Mutants application.

This file should have NO local imports to avoid circular dependencies.
"""

from __future__ import annotations

# Canonical ordering for player classes when rendering menus or normalizing
# player state. This list is intentionally stable to avoid churn in saved
# profiles and UI output.
CLASS_ORDER = ["Thief", "Priest", "Wizard", "Warrior", "Mage"]

# The default line for a monster's innate (natural) attack.
DEFAULT_INNATE_ATTACK_LINE = "The monster strikes you with a natural attack!"
