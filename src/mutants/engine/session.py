"""In-process session utilities for REPL state sharing."""
from __future__ import annotations

_ACTIVE_CLASS: str | None = None


def set_active_class(name: str | None) -> None:
    """Remember the currently selected class name for this process."""

    global _ACTIVE_CLASS
    _ACTIVE_CLASS = name


def get_active_class() -> str | None:
    """Return the class chosen during this process, if any."""

    return _ACTIVE_CLASS
