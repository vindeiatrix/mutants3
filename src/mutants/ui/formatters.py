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
from . import uicontract as UC
from . import item_display as idisp
from .textutils import harden_final_display

Segments = List[Segment]


def format_header(text: str) -> Segments:
    return [(HEADER, text)]


def format_compass(x: int, y: int) -> Segments:
    # Display coordinates without '+' for non-negative values (match BBS logs)
    east = f"{x}E"
    north = f"{y}N"
    return [(COMPASS_LABEL, "Compass:"), ("", " "), (COORDS, f"({east} : {north})")]


def _dir_word(name: str) -> str:
    return {
        "N": "north",
        "S": "south",
        "E": "east",
        "W": "west",
    }[name]


def format_direction_segments(dir_name: str, edge: EdgeDesc) -> Segments:
    word = _dir_word(dir_name)
    segments: Segments = [(DIR, word), ("", "  - ")]

    base = edge.get("base", 0)
    if base == 0:
        segments.append((DESC_CONT, UC.DESC_AREA_CONTINUES))
    elif base == 1:
        segments.append((DESC_TERRAIN, UC.DESC_WALL_OF_ICE))
    elif base == 2:
        segments.append((DESC_BOUNDARY, UC.DESC_ION_FORCE_FIELD))
    elif base == 3:
        state = edge.get("gate_state", 0)
        if state == 0:
            segments.append((DESC_GATE_OPEN, UC.DESC_OPEN_GATE))
        elif state == 1:
            segments.append((DESC_GATE_CLOSED, UC.DESC_CLOSED_GATE))
        elif state == 2:
            segments.append((DESC_GATE_LOCKED, UC.DESC_LOCKED_GATE))
    else:
        segments.append((DESC_CONT, ""))
    return segments


def format_monsters_here_tokens(monsters: List[Thing]) -> List[Segments]:
    lines: List[Segments] = []
    for m in monsters:
        lines.append([(MONSTER, f"{m['name']} is here.")])
    return lines


def format_ground_label() -> Segments:
    return [(LABEL, "On the ground lies:")]


def format_item(text: str) -> Segments:
    """Wrap item text (with article/numbering) in ITEM token."""
    return [(ITEM, text)]


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

# --- Group-aware string formatters ---------------------------------------
from . import groups as UG
from . import styles as st
import json
from .wrap import wrap_list, WRAP_DEBUG_OPTS
from ..app.trace import is_ui_trace_enabled


def format_compass_line(vm) -> str:
    """Return compass line, colored via group mapping."""
    text = vm.get("compass_str", "")
    return st.colorize_text(text, group=UG.COMPASS_LINE)


def format_direction_line(dir_key: str, edge: dict) -> str:
    """Return a direction line colored by open/blocked groups."""
    word = _dir_word(dir_key) if dir_key in {"N", "S", "E", "W"} else dir_key
    base = edge.get("base", 0)
    if base == 0:
        desc = UC.DESC_AREA_CONTINUES
        group = UG.DIR_OPEN
    elif base == 3:
        gs = edge.get("gate_state", 0)
        if gs == 0:
            desc = UC.DESC_OPEN_GATE
            group = UG.DIR_OPEN
        elif gs == 2:
            desc = UC.DESC_LOCKED_GATE
            group = UG.DIR_BLOCKED
        else:
            desc = UC.DESC_CLOSED_GATE
            group = UG.DIR_BLOCKED
    else:
        desc = edge.get("desc", "")
        group = UG.DIR_BLOCKED
    return st.colorize_text(UC.DIR_LINE_FMT.format(word, desc), group=group)


def format_ground_header() -> str:
    """Fixed header for the ground block."""
    return st.colorize_text(UC.GROUND_HEADER, group=UG.HEADER)


def format_ground_items(item_ids: list[str]) -> list[str]:
    """Return wrapped ground item lines for *item_ids* using canonical rules."""
    if not item_ids:
        return []
    names = [idisp.canonical_name(i) for i in item_ids]
    numbered = idisp.number_duplicates(names)
    display = [harden_final_display(idisp.with_article(n)) for n in numbered]
    fb = None
    if is_ui_trace_enabled():
        from ..app.context import current_context
        ctx = current_context()
        fb = ctx.get("feedback_bus") if ctx else None
    if fb:
        raw = "On the ground lies: " + ", ".join(display) + "."
        fb.push(
            "SYSTEM/INFO",
            f'UI/GROUND raw={json.dumps(raw, ensure_ascii=False)}',
        )
    lines = wrap_list(display, width=UC.UI_WRAP_WIDTH)
    if fb:
        fb.push(
            "SYSTEM/INFO",
            f'UI/GROUND wrap width={UC.UI_WRAP_WIDTH} '
            f'opts={json.dumps(WRAP_DEBUG_OPTS, sort_keys=True)} '
            f'lines={json.dumps(lines, ensure_ascii=False)}',
        )
    return lines


def format_monsters_here(names: list[str]) -> str:
    """
    Monsters presence line(s):
      - 1 name: "<Name> is here."
      - 2+ names: "A, B, and C are here with you." (always include comma before 'and')
    """
    clean = []
    for n in names:
        if isinstance(n, dict):
            n = n.get("name", "")
        s = str(n).strip()
        if s:
            clean.append(s)
    if not clean:
        return ""
    if len(clean) == 1:
        text = f"{clean[0]} is here."
    elif len(clean) == 2:
        text = f"{clean[0]}, and {clean[1]} are here with you."
    else:
        text = f"{', '.join(clean[:-1])}, and {clean[-1]} are here with you."
    return st.colorize_text(text, group=UG.FEEDBACK_INFO)


def format_cue_line(text: str) -> str:
    """
    Print a single cue line verbatim (caller handles separator placement).
    Examples from originals include:
      - "You see shadows to the south."
      - "You hear loud sounds of yelling and screaming to the west."
    """
    return st.colorize_text(str(text).rstrip(), group=UG.FEEDBACK_INFO)


def format_room_title(title: str) -> str:
    return st.colorize_text(title, group=UG.ROOM_TITLE)


def format_room_desc(desc: str) -> str:
    return st.colorize_text(desc, group=UG.ROOM_DESC)

