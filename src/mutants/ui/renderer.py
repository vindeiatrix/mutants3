"""Renderer turning room view-models into tokenized/ANSI lines."""
from __future__ import annotations

from typing import List

from . import constants as c
from . import formatters as fmt
from . import styles
from .viewmodels import RoomVM
from .wrap import wrap_list

SegmentLine = List[styles.Segment]


def render_token_lines(vm: RoomVM, width: int = c.WIDTH) -> List[SegmentLine]:
    lines: List[SegmentLine] = []

    lines.append(fmt.format_header(vm["header"]))

    coords = vm["coords"]
    lines.append(fmt.format_compass(coords["x"], coords["y"]))

    dirs = vm.get("dirs", {})
    for d in c.DIR_ORDER:
        edge = dirs.get(d, {"base": 0})
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
        lines.append([("", "***")])
        for ev in events:
            lines.append([( "", ev)])

    shadows = vm.get("shadows", [])
    shadow_line = fmt.format_shadows(shadows)
    if shadow_line:
        lines.append(shadow_line)

    return lines


def render(vm: RoomVM, width: int = c.WIDTH, palette=styles.BBS_PALETTE) -> List[str]:
    """Render *vm* to a list of ANSI strings."""
    lines = render_token_lines(vm, width)
    return [styles.resolve_segments(segs, palette) for segs in lines]


def token_debug_lines(vm: RoomVM, width: int = c.WIDTH) -> List[str]:
    """Return token-debug strings for testing."""
    return [styles.tagged_string(line) for line in render_token_lines(vm, width)]
