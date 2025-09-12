"""Helpers for rendering item display names safely."""

from __future__ import annotations


def harden_display_nonbreak(s: str) -> str:
    """Return *s* with hyphen and article hardened using non-breaking forms.

    This is UI-only and must be applied only to final display strings
    (after article and numbering).
    """

    if not s:
        return s
    hardened = s.replace("-", "\u2011")
    if " " in hardened:
        first = hardened.find(" ")
        hardened = hardened[:first] + "\u00A0" + hardened[first + 1 :]
    return hardened

