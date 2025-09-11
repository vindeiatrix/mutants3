"""Pure formatters that produce tokenized text segments."""
from __future__ import annotations

from typing import List

from . import constants as c
from .styles import (
    COMPASS_LABEL,
    COORDS,
    DESC_BOUNDARY,
    DESC_CONT,
    DESC_GATE_CLOSED,
    DESC_GATE_LOCKED,
    DESC_GATE_OPEN,
    DESC_TERRAIN,
    DIR,
    HEADER,
    ITEM,
    LABEL,
    MONSTER,
    SHADOWS_LABEL,
    Segment,
)
from .viewmodels import EdgeDesc, Thing

Segments = List[Segment]


def format_header(text: str) -> Segments:
    return [(HEADER, text)]


def format_compass(x: int, y: int) -> Segments:
+   # Display coordinates without '+' for non-negative values (match BBS logs)
+   east = f"{x}E"
+   north = f"{y}N"
+   return [(c.COMPASS_LABEL, "Compass:"), ("", " "), (c.COORDS, f"({east} : {north})")]


def _dir_word(name: str) -> str:
    return {
        "N": "north",
        "S": "south",
        "E": "east",
        "W": "west",
    }[name]


def format_direction_line(dir_name: str, edge: EdgeDesc) -> Segments:
    word = _dir_word(dir_name)
    pad = c.DIR_LABEL_PAD - len(word)
    segments: Segments = [(DIR, word), ("", " " * pad + "  - ")]

    base = edge.get("base", 0)
    if base == 0:
        segments.append((DESC_CONT, "area continues."))
    elif base == 1:
        segments.append((DESC_TERRAIN, "terrain blocks the way."))
    elif base == 2:
        segments.append((DESC_BOUNDARY, "boundary."))
    elif base == 3:
        state = edge.get("gate_state", 0)
        if state == 0:
            segments.append((DESC_GATE_OPEN, "open gate."))
        elif state == 1:
            segments.append((DESC_GATE_CLOSED, "closed gate."))
        elif state == 2:
            key = edge.get("key_type")
            if key is not None:
                segments.append((DESC_GATE_LOCKED, f"locked gate (key {key})."))
            else:
                segments.append((DESC_GATE_LOCKED, "locked gate."))
    else:
        segments.append((DESC_CONT, ""))
    return segments


def format_monsters_here(monsters: List[Thing]) -> List[Segments]:
    lines: List[Segments] = []
    for m in monsters:
        lines.append([(MONSTER, f"{m['name']} is here.")])
    return lines


def format_ground_label() -> Segments:
    return [(LABEL, "On the ground lies:")]


def format_item(name: str) -> Segments:
    return [(ITEM, f"A {name}")]


def format_shadows(dirs: List[str]) -> Segments | None:
    if not dirs:
        return None
    words = []
    order = ["E", "S", "W", "N"]
    for d in order:
        if d in dirs:
            words.append(_dir_word(d))
    text = ", ".join(words)
    return [(SHADOWS_LABEL, f"You see shadows to the {text}.")]
