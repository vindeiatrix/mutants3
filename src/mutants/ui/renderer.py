"""Renderer turning room view-models into tokenized/ANSI lines."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import constants as c
from . import formatters as fmt
from . import styles
from .viewmodels import RoomVM
from .wrap import wrap_list

SegmentLine = List[styles.Segment]


def _feedback_token(kind: str) -> str:
    mapping = {
        "SYSTEM/OK": styles.FEED_SYS_OK,
        "SYSTEM/WARN": styles.FEED_SYS_WARN,
        "SYSTEM/ERR": styles.FEED_SYS_ERR,
        "MOVE/OK": styles.FEED_MOVE,
        "MOVE/BLOCKED": styles.FEED_BLOCK,
        "COMBAT/HIT": styles.FEED_COMBAT,
        "COMBAT/CRIT": styles.FEED_CRIT,
        "COMBAT/TAUNT": styles.FEED_TAUNT,
        "LOOT/PICKUP": styles.FEED_LOOT,
        "LOOT/DROP": styles.FEED_LOOT,
        "SPELL/CAST": styles.FEED_SPELL,
        "SPELL/FAIL": styles.FEED_SPELL,
        "DEBUG": styles.FEED_DEBUG,
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

    # Show only open/continuous directions (plain tiles): omit obstacles.
    dirs = vm.get("dirs", {})
    for d in c.DIR_ORDER:
        edge = dirs.get(d, {"base": 0})
        # Plain/open edges have base == 0; blocked/gates/boundaries are non-zero.
        if edge.get("base", 0) == 0:
            lines.append(fmt.format_direction_line(d, edge))

    lines.append([("", "***")])

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
    return [styles.resolve_segments(segs, palette) for segs in lines]


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

    dirs = vm.get("dirs", {})
    for d in c.DIR_ORDER:
        edge = dirs.get(d, {"base": 0})
        lines.append(fmt.format_direction_line_colored(d, edge))

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
        styles.tagged_string(line)
        for line in render_token_lines(vm, feedback_events, width)
    ]
