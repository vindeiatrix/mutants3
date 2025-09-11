"""Renderer turning room view-models into tokenized/ANSI lines."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import constants as c
from . import formatters as fmt
from . import uicontract as UC
from . import styles as st
from .viewmodels import RoomVM
from .wrap import wrap_list
import os
import logging

SegmentLine = List[st.Segment]


def _feedback_token(kind: str) -> str:
    mapping = {
        "SYSTEM/OK": st.FEED_SYS_OK,
        "SYSTEM/WARN": st.FEED_SYS_WARN,
        "SYSTEM/ERR": st.FEED_SYS_ERR,
        "MOVE/OK": st.FEED_MOVE,
        "MOVE/BLOCKED": st.FEED_BLOCK,
        "COMBAT/HIT": st.FEED_COMBAT,
        "COMBAT/CRIT": st.FEED_CRIT,
        "COMBAT/TAUNT": st.FEED_TAUNT,
        "LOOT/PICKUP": st.FEED_LOOT,
        "LOOT/DROP": st.FEED_LOOT,
        "SPELL/CAST": st.FEED_SPELL,
        "SPELL/FAIL": st.FEED_SPELL,
        "DEBUG": st.FEED_DEBUG,
    }
    for prefix, token in mapping.items():
        if kind.startswith(prefix):
            return token
    return ""


def render_token_lines(
    vm: RoomVM, feedback_events: Optional[List[dict]] = None, width: int = c.WIDTH
) -> List[SegmentLine]:
    lines: List[SegmentLine] = []

    lines.append(fmt.format_header(vm["header"]))

    coords = vm["coords"]
    lines.append(fmt.format_compass(coords["x"], coords["y"]))

    # Directions list must be OPEN-ONLY by construction.
    # Prefer vm["dirs_open"] if present; otherwise derive from vm["dirs"].
    raw_dirs = vm.get("dirs", {}) or {}
    dirs_open = vm.get("dirs_open")
    if dirs_open is None:
        # Derive open-only dict (base == 0 means "area continues"/open).
        dirs_open = {k: v for k, v in raw_dirs.items() if v.get("base", 0) == 0}

    DEV = os.environ.get("MUTANTS_DEV") == "1"
    logger = logging.getLogger(__name__)

    for d in c.DIR_ORDER:
        edge = dirs_open.get(d)
        if not edge:
            continue
        # Guardrail: if something non-open leaked in, drop it and warn (or assert in dev).
        if edge.get("base", 0) != 0:
            if DEV:
                assert False, f"ui: non-open edge leaked into dirs_open: {d}"
            else:
                logger.warning("ui: dropped non-open edge in dirs_open: %s", d)
            continue
        lines.append(fmt.format_direction_segments(d, edge))

    sep_line = [("", UC.SEPARATOR_LINE)]
    if not lines or lines[-1] != sep_line:
        lines.append(sep_line)

    # Monsters present
    monsters = vm.get("monsters_here", [])
    for segs in fmt.format_monsters_here(monsters):
        lines.append(segs)

    items = vm.get("ground_items", [])
    if items:
        lines.append(fmt.format_ground_label())
        item_segs = [fmt.format_item(t["name"]) for t in items]
        lines.extend(wrap_list(item_segs, width))

    events = vm.get("events", [])
    if events:
        for ev in events:
            lines.append([("", ev)])

    shadows = vm.get("shadows", [])
    shadow_line = fmt.format_shadows(shadows)
    if shadow_line:
        lines.append(shadow_line)

    if feedback_events:
        for ev in feedback_events:
            token = _feedback_token(ev.get("kind", ""))
            lines.append([(token, ev.get("text", ""))])

    return lines


def render_tokenized(
    vm: RoomVM,
    feedback_events: Optional[List[dict]] = None,
    width: int = c.WIDTH,
    palette: Dict[str, str] | None = None,
) -> List[str]:
    """Legacy renderer that resolves tokens via *palette*."""
    if palette is None:
        palette = {}
    lines = render_token_lines(vm, feedback_events, width)
    return [st.resolve_segments(segs, palette) for segs in lines]


def render(
    vm: RoomVM,
    feedback_events: Optional[List[dict]] = None,
    width: int = c.WIDTH,
    palette: Dict[str, str] | None = None,
) -> List[str]:
    """Render *vm* to ANSI strings using group-based colors."""
    lines: List[str] = []
    header = vm.get("header")
    if header:
        lines.append(fmt.format_room_title(header))

    coords = vm.get("coords", {})
    compass_str = f"Compass: ({coords.get('x',0)}E : {coords.get('y',0)}N)"
    vm_local = {"compass_str": compass_str}
    lines.append(fmt.format_compass_line(vm_local))

    # Directions list must be OPEN-ONLY by construction.
    raw_dirs = vm.get("dirs", {}) or {}
    dirs_open = vm.get("dirs_open")
    if dirs_open is None:
        dirs_open = {k: v for k, v in raw_dirs.items() if v.get("base", 0) == 0}

    DEV = os.environ.get("MUTANTS_DEV") == "1"
    logger = logging.getLogger(__name__)

    for d in c.DIR_ORDER:
        edge = dirs_open.get(d)
        if not edge:
            continue
        if edge.get("base", 0) != 0:
            if DEV:
                assert False, f"ui: non-open edge leaked into dirs_open: {d}"
            else:
                logger.warning("ui: dropped non-open edge in dirs_open: %s", d)
            continue
        lines.append(fmt.format_direction_line(d, edge))

    if not lines or lines[-1] != UC.SEPARATOR_LINE:
        lines.append(UC.SEPARATOR_LINE)

    monsters = vm.get("monsters_here", [])
    for m in monsters:
        name = m.get("name", "?")
        lines.append(f"{name} is here.")

    items = vm.get("ground_items", [])
    for it in items:
        name = it.get("name", "?")
        lines.append(f"A {name}.")

    events = vm.get("events", [])
    lines.extend(events)

    shadows = vm.get("shadows", [])
    if shadows:
        dirs_words = []
        for d in ["E", "S", "W", "N"]:
            if d in shadows:
                dirs_words.append(fmt._dir_word(d))  # type: ignore[attr-defined]
        if dirs_words:
            lines.append(f"You see shadows to the {', '.join(dirs_words)}.")

    if feedback_events:
        for ev in feedback_events:
            lines.append(ev.get("text", ""))

    return lines


def token_debug_lines(
    vm: RoomVM, feedback_events: Optional[List[dict]] = None, width: int = c.WIDTH
) -> List[str]:
    """Return token-debug strings for testing."""
    return [
        st.tagged_string(line)
        for line in render_token_lines(vm, feedback_events, width)
    ]
