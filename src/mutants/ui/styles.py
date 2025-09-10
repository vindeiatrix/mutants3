"""Token definitions and helpers for styling the UI."""
from __future__ import annotations

from typing import Dict, List, Tuple

Segment = Tuple[str, str]

# Token names
HEADER = "HEADER"
COMPASS_LABEL = "COMPASS_LABEL"
COORDS = "COORDS"
DIR = "DIR"
DESC_CONT = "DESC_CONT"
DESC_TERRAIN = "DESC_TERRAIN"
DESC_BOUNDARY = "DESC_BOUNDARY"
DESC_GATE_OPEN = "DESC_GATE_OPEN"
DESC_GATE_CLOSED = "DESC_GATE_CLOSED"
DESC_GATE_LOCKED = "DESC_GATE_LOCKED"
LABEL = "LABEL"
ITEM = "ITEM"
MONSTER = "MONSTER"
SHADOWS_LABEL = "SHADOWS_LABEL"
FEED_SYS_OK = "FEED_SYS_OK"
FEED_SYS_WARN = "FEED_SYS_WARN"
FEED_SYS_ERR = "FEED_SYS_ERR"
FEED_MOVE = "FEED_MOVE"
FEED_BLOCK = "FEED_BLOCK"
FEED_COMBAT = "FEED_COMBAT"
FEED_CRIT = "FEED_CRIT"
FEED_TAUNT = "FEED_TAUNT"
FEED_LOOT = "FEED_LOOT"
FEED_SPELL = "FEED_SPELL"
FEED_DEBUG = "FEED_DEBUG"
RESET = "RESET"


def resolve_segments(segments: List[Segment], palette: Dict[str, str]) -> str:
    """Resolve segments into an ANSI string using *palette*."""
    pieces: List[str] = []
    reset = palette.get(RESET, "\x1b[0m")
    for token, text in segments:
        color = palette.get(token, "")
        if color:
            pieces.append(f"{color}{text}{reset}")
        else:
            pieces.append(text)
    return "".join(pieces)


def tagged_string(segments: List[Segment]) -> str:
    """Convert segments into a debug string with tags."""
    out: List[str] = []
    for token, text in segments:
        if token:
            out.append(f"<{token}>{text}</{token}>")
        else:
            out.append(text)
    return "".join(out)
