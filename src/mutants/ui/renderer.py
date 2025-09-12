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
from ..engine import edge_resolver as ER
from ..registries import dynamics as dyn
from ..app import context as appctx

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

    # Validate directions against the passability engine to prevent drift.
    # (We keep the existing VM feed, but drop any direction the resolver blocks.)
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
        # Cross-check with resolver (single source of truth for movement).
        player = getattr(appctx, "player", None)
        world = getattr(appctx, "world", None)
        if player is not None and world is not None:
            try:
                year = getattr(player, "year")
                x = getattr(player, "x")
                y = getattr(player, "y")
                dec = ER.resolve(world, dyn, year, x, y, d, actor={})
                if not dec.passable:
                    if DEV:
                        assert False, f"ui: resolver blocked direction {d} at ({x},{y})"
                    else:
                        logger.warning(
                            "ui: dropped dir %s (resolver blocked) cur=%r nbr=%r",
                            d,
                            dec.cur_raw,
                            dec.nbr_raw,
                        )
                    continue
            except Exception as e:
                logger.warning("ui: resolver check failed for dir %s: %s", d, e)
        lines.append(fmt.format_direction_segments(d, edge))

    sep_line = [("", UC.SEPARATOR_LINE)]
    if not lines or lines[-1] != sep_line:
        lines.append(sep_line)

    # Monsters present
    monsters = vm.get("monsters_here", [])
    for segs in fmt.format_monsters_here_tokens(monsters):
        lines.append(segs)

    items = vm.get("ground_items", [])
    if items:
        lines.append(fmt.format_ground_label())
        item_segs = [
            fmt.format_item(t if isinstance(t, str) else t.get("name", "?"))
            for t in items
        ]
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

    # Validate directions against the passability engine to prevent drift.
    # (We keep the existing VM feed, but drop any direction the resolver blocks.)
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
        # Cross-check with resolver (single source of truth for movement).
        player = getattr(appctx, "player", None)
        world = getattr(appctx, "world", None)
        if player is not None and world is not None:
            try:
                year = getattr(player, "year")
                x = getattr(player, "x")
                y = getattr(player, "y")
                dec = ER.resolve(world, dyn, year, x, y, d, actor={})
                if not dec.passable:
                    if DEV:
                        assert False, f"ui: resolver blocked direction {d} at ({x},{y})"
                    else:
                        logger.warning(
                            "ui: dropped dir %s (resolver blocked) cur=%r nbr=%r",
                            d,
                            dec.cur_raw,
                            dec.nbr_raw,
                        )
                    continue
            except Exception as e:
                logger.warning("ui: resolver check failed for dir %s: %s", d, e)
        lines.append(fmt.format_direction_line(d, edge))

    # ------- Build blocks instead of emitting separators inline -------
    block_core = list(lines)
    lines = []

    # ---- Ground Block (optional) ----
    block_ground: list[str] = []
    has_ground = bool(vm.get("has_ground", False))
    ground_items = vm.get("ground_items") or []
    if has_ground:
        if not ground_items:
            if DEV:
                assert False, "ui: has_ground=True but ground_items is empty"
            else:
                logger.warning(
                    "ui: dropping empty ground block (has_ground=True, no items)"
                )
        else:
            block_ground.append(fmt.format_ground_header())
            for ln in fmt.format_ground_list(ground_items):
                block_ground.append(ln)

    # ---- Monsters block (optional, after Ground) ----
    block_monsters: list[str] = []
    monsters = vm.get("monsters_here") or []
    if monsters:
        mline = fmt.format_monsters_here(monsters)
        if mline:
            block_monsters.append(mline)

    # ---- Cues block (optional, after Monsters) ----
    block_cues: list[str] = []
    cues = vm.get("cues_lines") or []
    if cues:
        for idx, cue in enumerate(cues):
            block_cues.append(fmt.format_cue_line(cue))
            if idx < len(cues) - 1:
                block_cues.append(UC.SEPARATOR_LINE)

    # ---- Join blocks with separators between non-empty blocks only ----
    def _join_with_separators(blocks: list[list[str]]) -> list[str]:
        out: list[str] = []
        first = True
        for b in blocks:
            if not b:
                continue
            if not first:
                out.append(UC.SEPARATOR_LINE)
            out.extend(b)
            first = False
        return out

    def _assert_no_sep_violations(out_lines: list[str]) -> list[str]:
        if not out_lines:
            return out_lines
        if out_lines[0] == UC.SEPARATOR_LINE or out_lines[-1] == UC.SEPARATOR_LINE:
            if DEV:
                assert False, "ui: separator at frame boundary"
            while out_lines and out_lines[0] == UC.SEPARATOR_LINE:
                out_lines.pop(0)
            while out_lines and out_lines[-1] == UC.SEPARATOR_LINE:
                out_lines.pop()
        i = 1
        while i < len(out_lines):
            if (
                out_lines[i] == UC.SEPARATOR_LINE
                and out_lines[i - 1] == UC.SEPARATOR_LINE
            ):
                if DEV:
                    assert False, "ui: consecutive separators"
                out_lines.pop(i)
            else:
                i += 1
        return out_lines

    blocks = [block_core, block_ground, block_monsters, block_cues]
    lines = _join_with_separators(blocks)
    lines = _assert_no_sep_violations(lines)

    if feedback_events:
        for ev in feedback_events:
            lines.append(ev.get("text", ""))

    return lines


# Development helper used by `logs verify separators`
def verify_separators_scenarios() -> tuple[int, list[str]]:
    """Run synthetic scenarios to ensure separator invariants."""
    failures: list[str] = []
    ok = 0

    def check(name: str, blocks: list[list[str]], expect_last_is_sep: bool = False):
        nonlocal ok

        def join(blks: list[list[str]]) -> list[str]:
            out: list[str] = []
            first = True
            for b in blks:
                if not b:
                    continue
                if not first:
                    out.append(UC.SEPARATOR_LINE)
                out.extend(b)
                first = False
            return out

        out = join(blocks)
        if out and out[0] == UC.SEPARATOR_LINE:
            failures.append(f"{name}: leading separator")
            return
        if out and out[-1] == UC.SEPARATOR_LINE and not expect_last_is_sep:
            failures.append(f"{name}: trailing separator")
            return
        for i in range(1, len(out)):
            if out[i] == UC.SEPARATOR_LINE and out[i - 1] == UC.SEPARATOR_LINE:
                failures.append(f"{name}: double separator @ {i}")
                return
        ok += 1

    A = ["Room", "Compass", "Dirs"]
    G = ["On the ground lies:", "item1, item2."]
    M = ["Monster-Alpha is here."]
    C = [
        "You see shadows to the south.",
        UC.SEPARATOR_LINE,
        "You hear footsteps to the west.",
    ]

    check("core-only", [A])
    check("core+ground", [A, G])
    check("core+ground+monsters", [A, G, M])
    check("core+monsters", [A, M])
    check("core+cues(2)", [A, C])
    check("ground-only", [G])

    return ok, failures


def token_debug_lines(
    vm: RoomVM, feedback_events: Optional[List[dict]] = None, width: int = c.WIDTH
) -> List[str]:
    """Return token-debug strings for testing."""
    return [
        st.tagged_string(line)
        for line in render_token_lines(vm, feedback_events, width)
    ]
