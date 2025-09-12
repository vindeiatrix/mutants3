"""Helpers for wrapping UI text without breaking on hyphens."""

from __future__ import annotations

import json
import logging
from textwrap import TextWrapper

from mutants.app import trace as traceflags

DEFAULT_WIDTH = 80

# Centralized config for all UI text wrapping. Exposed for debug logging.
WRAP_DEBUG_OPTS = dict(
    break_on_hyphens=False,
    break_long_words=False,
    replace_whitespace=False,
    drop_whitespace=False,
)


def wrap(text: str, width: int = DEFAULT_WIDTH) -> list[str]:
    """Return wrapped lines of *text* with safe non-breaking defaults."""

    w = TextWrapper(width=width, **WRAP_DEBUG_OPTS)
    return w.wrap(text)


def wrap_segments(segments: list[str], width: int = DEFAULT_WIDTH) -> list[str]:
    """Wrap pre-split *segments* preserving non-breaking hyphen rules."""

    w = TextWrapper(width=width, **WRAP_DEBUG_OPTS)
    lines: list[str] = []
    for seg in segments:
        if not seg:
            continue
        lines.extend(w.wrap(seg))
    return [ln.rstrip() for ln in lines]


def wrap_list(items: list[str], width: int = DEFAULT_WIDTH, sep: str = ", ") -> list[str]:
    """Join *items* with *sep* and wrap the result with non-breaking hyphen rules."""

    joined = sep.join(items) + "."
    if traceflags.get_flag("ui"):
        logging.getLogger(__name__).info(
            "UI/GROUND raw=%s", json.dumps(joined, ensure_ascii=False)
        )
    lines = wrap(joined, width=width)
    lines = [ln.rstrip() for ln in lines]
    if traceflags.get_flag("ui"):
        logging.getLogger(__name__).info(
            "UI/GROUND wrap width=%d opts=%s lines=%s",
            width,
            json.dumps(WRAP_DEBUG_OPTS, sort_keys=True),
            json.dumps(lines, ensure_ascii=False),
        )
    return lines

