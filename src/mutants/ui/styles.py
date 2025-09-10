"""ANSI styling helpers for the UI renderer."""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import constants as c

Segment = Tuple[str, str]

# Basic BBS-style palette
BBS_PALETTE: Dict[str, str] = {
    c.HEADER: "\x1b[1;37m",  # bright white
    c.COMPASS_LABEL: "\x1b[36m",  # cyan
    c.COORDS: "\x1b[37m",  # white
    c.DIR: "\x1b[33m",  # yellow
    c.DESC_CONT: "\x1b[37m",
    c.DESC_TERRAIN: "\x1b[31m",  # red
    c.DESC_BOUNDARY: "\x1b[35m",  # magenta
    c.DESC_GATE_OPEN: "\x1b[32m",  # green
    c.DESC_GATE_CLOSED: "\x1b[33m",  # yellow
    c.DESC_GATE_LOCKED: "\x1b[31m",  # red
    c.LABEL: "\x1b[35m",
    c.ITEM: "\x1b[36m",
    c.MONSTER: "\x1b[31m",
    c.SHADOWS_LABEL: "\x1b[90m",  # dark gray
}

# Monochrome palette used for tests (no colors)
MONO_PALETTE: Dict[str, str] = {token: "" for token in BBS_PALETTE.keys()}


def resolve_segments(segments: List[Segment], palette: Dict[str, str]) -> str:
    """Resolve a list of segments into a single ANSI string using *palette*."""
    pieces: List[str] = []
    reset = "\x1b[0m"
    for token, text in segments:
        color = palette.get(token, "")
        if color:
            pieces.append(f"{color}{text}{reset}")
        else:
            pieces.append(text)
    return "".join(pieces)


def tagged_string(segments: List[Segment]) -> str:
    """Convert segments into a debug string with XML-like tags."""
    out: List[str] = []
    for token, text in segments:
        if token:
            out.append(f"<{token}>{text}</{token}>")
        else:
            out.append(text)
    return "".join(out)
