"""Helpers for rendering item display names safely."""

from __future__ import annotations


def _no_break_hyphens(s: str) -> str:
    """Replace ASCII hyphen with U+2011 (no-break hyphen) for display only."""

    return s.replace("-", "\u2011")


def display_name_for_item(name: str) -> str:
    """Return *name* with hyphens rendered as non-breaking."""

    hardened = _no_break_hyphens(name)
    if " " in hardened:
        first = hardened.find(" ")
        hardened = hardened[:first] + "\u00a0" + hardened[first + 1 :]
    return hardened

