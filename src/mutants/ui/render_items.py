"""Helpers for rendering item display names safely."""

from __future__ import annotations

from .textutils import harden_final_display


def harden_display_nonbreak(s: str) -> str:
    """Backward compat wrapper for :func:`harden_final_display`."""
    return harden_final_display(s)

