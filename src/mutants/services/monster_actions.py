"""Placeholder monster action helpers.

These routines will be fleshed out by subsequent tasks. The AI tick hook only
needs an entry point it can call for now, so the implementation is a no-op.
"""
from __future__ import annotations

from typing import Any


def execute_random_action(monster: Any, ctx: Any, *, rng: Any | None = None) -> None:
    """Execute a placeholder action for *monster*.

    The implementation intentionally does nothing; it exists so the AI turn
    hook can invoke a stable API that later tasks will replace with concrete
    behaviour.
    """

    return None

