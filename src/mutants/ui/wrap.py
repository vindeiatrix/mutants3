"""Helpers for wrapping UI text without breaking on hyphens."""

from __future__ import annotations

from textwrap import TextWrapper

DEFAULT_WIDTH = 80

# Centralized config for all UI text wrapping.
_WRAP_KW = dict(
    break_on_hyphens=False,
    break_long_words=False,
    replace_whitespace=False,
    drop_whitespace=False,
)


def wrap(text: str, width: int = DEFAULT_WIDTH) -> list[str]:
    """Return wrapped lines of *text* with safe non-breaking defaults."""

    w = TextWrapper(width=width, **_WRAP_KW)
    return w.wrap(text)


def wrap_segments(segments: list[str], width: int = DEFAULT_WIDTH) -> list[str]:
    """Wrap pre-split *segments* preserving non-breaking hyphen rules."""

    w = TextWrapper(width=width, **_WRAP_KW)
    lines: list[str] = []
    for seg in segments:
        if not seg:
            continue
        lines.extend(w.wrap(seg))
    return [ln.rstrip() for ln in lines]


def wrap_list(items: list[str], width: int = DEFAULT_WIDTH, sep: str = ", ") -> list[str]:
    """Join *items* with *sep* and wrap the result with non-breaking hyphen rules."""

    joined = sep.join(items) + "."
    lines = wrap(joined, width=width)
    return [ln.rstrip() for ln in lines]

