"""Helpers for wrapping ANSI-tagged text segments."""
from __future__ import annotations

import re
from typing import List
from textwrap import TextWrapper

from .styles import ITEM, Segment

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

DEFAULT_WIDTH = 80


def visible_len(s: str) -> int:
    """Return the printable length of *s*, ignoring ANSI codes."""
    return len(ANSI_RE.sub("", s))


def wrap_segments(segments: List[Segment], width: int) -> List[List[Segment]]:
    """Hard-wrap *segments* to *width* columns preserving token boundaries."""
    lines: List[List[Segment]] = []
    current: List[Segment] = []
    current_len = 0

    for token, text in segments:
        seg_len = visible_len(text)
        if current_len + seg_len > width and current_len > 0:
            # finish current line
            if current and current[-1][1].endswith(" "):
                tok, txt = current[-1]
                current[-1] = (tok, txt.rstrip(" "))
            lines.append(current)
            current = []
            current_len = 0

        # skip leading spaces
        if token == ITEM and text == " " and current_len == 0:
            continue

        if current and current[-1][0] == token:
            current[-1] = (token, current[-1][1] + text)
        else:
            current.append((token, text))
        current_len += seg_len

    if current:
        if current[-1][1].endswith(" "):
            tok, txt = current[-1]
            current[-1] = (tok, txt.rstrip(" "))
        lines.append(current)
    return lines


def wrap_list(items: List[List[Segment]], width: int) -> List[List[Segment]]:
    """Wrap a list of item segments with comma separation and trailing period."""
    segments: List[Segment] = []
    last_index = len(items) - 1
    for idx, item_segments in enumerate(items):
        for token, text in item_segments:
            if idx < last_index:
                segments.append((token, text + ","))
                segments.append((token, " "))
            else:
                segments.append((token, text + "."))
    return wrap_segments(segments, width)


def wrap(text: str, width: int = DEFAULT_WIDTH) -> List[str]:
    """Return wrapped lines of *text* without breaking on hyphens."""
    w = TextWrapper(
        width=width,
        break_on_hyphens=False,
        break_long_words=False,
        replace_whitespace=False,
        drop_whitespace=False,
    )
    return w.wrap(text)
