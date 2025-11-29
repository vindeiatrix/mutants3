"""Renderer turning room view-models into tokenized/ANSI lines."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from . import constants as c
from . import formatters as fmt
from . import uicontract as UC
from . import styles as st
from .viewmodels import RoomVM
from .wrap import wrap_list, WRAP_DEBUG_OPTS
from . import item_display as idisp
from .textutils import harden_final_display, resolve_feedback_text
import os
import logging
import json
from ..engine import edge_resolver as ER
from ..registries import dynamics as dyn
from ..services import player_state as pstate
from ..app import context as appctx
from ..app.trace import is_ui_trace_enabled

LOG = logging.getLogger(__name__)

SegmentLine = List[st.Segment]


def _normalize_player_name(value: Any) -> Optional[str]:
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    return None


def _render_monsters(vm: RoomVM) -> tuple[List[SegmentLine], list[Any]]:
    coords = vm.get("coords") or {}
    year = coords.get("year")
    x = coords.get("x")
    y = coords.get("y")
    LOG.debug(
        ">>> _render_monsters called for %s,%s,%s", year, x, y
    )

    raw_monsters = vm.get("monsters_here") or []
    if isinstance(raw_monsters, list):
        monsters_here = list(raw_monsters)
    else:
        try:
            monsters_here = list(raw_monsters)
        except TypeError:
            monsters_here = [raw_monsters]

    _incoming = monsters_here
    incoming_ids: list[Any] = []
    incoming_names: list[Any] = []
    for entry in _incoming:
        if isinstance(entry, Mapping):
            ident = entry.get("instance_id") or entry.get("id")
            incoming_ids.append(str(ident) if ident is not None else None)
            incoming_names.append(entry.get("name"))
        else:
            incoming_ids.append(None)
            incoming_names.append(str(entry))
    LOG.debug(
        "--- _render_monsters received %d monsters from list_at. ids=%s names=%s",
        len(_incoming),
        incoming_ids,
        incoming_names,
    )

    lines: list[str] = []
    for monster in monsters_here:
        if isinstance(monster, Mapping):
            name = str(monster.get("name", "")).strip()
        else:
            name = str(monster).strip()
        if not name:
            continue
        lines.append(f"{name} is here.")

    LOG.debug("--- _render_monsters lines before grouping: %s", lines)

    def _group_lines(values: list[str]) -> list[tuple[str, int]]:
        order: list[str] = []
        counts: dict[str, int] = {}
        for value in values:
            if value not in counts:
                order.append(value)
                counts[value] = 1
            else:
                counts[value] += 1
        return [(value, counts[value]) for value in order]

    groups = _group_lines(lines)

    parts: list[str] = []
    for name_line, count in groups:
        if count == 1:
            parts.append(name_line)
        else:
            name_only = name_line.rsplit(" is here.", 1)[0]
            parts.append(f"{name_only} ({count})")

    LOG.debug("--- _render_monsters parts after grouping: %s", parts)

    if not parts:
        return [], monsters_here

    processed_parts: list[str] = []
    for part_str in parts:
        if " is here." in part_str:
            processed_parts.append(part_str.rsplit(" is here.", 1)[0])
        else:
            processed_parts.append(part_str)

    if len(processed_parts) == 1:
        name_str = processed_parts[0]
        suffix = " is here." if not name_str.endswith(")") else " are here."
        text = f"{name_str}{suffix}"
    elif len(processed_parts) == 2:
        text = (
            f"{processed_parts[0]}, and {processed_parts[1]} are here with you."
        )
    else:
        text = (
            f"{', '.join(processed_parts[:-1])}, and {processed_parts[-1]} are here."
        )

    return [[(st.MONSTER, text)]], monsters_here


def _with_player_display_name(
    event: Mapping[str, Any] | None, fallback: str
) -> Mapping[str, Any] | Any:
    if not isinstance(event, Mapping):
        return event  # type: ignore[return-value]
    payload = dict(event)
    name = _normalize_player_name(payload.get("player_name")) or fallback
    payload["player_name"] = name
    player_label = _normalize_player_name(payload.get("player")) or name
    payload["player"] = player_label
    return payload


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
        "COMBAT/INFO": st.FEED_COMBAT,
        "COMBAT/READY": st.FEED_TAUNT,
        "COMBAT/HEAL": st.FEED_COMBAT,
        "COMBAT/HEAL_MONSTER": st.FEED_COMBAT,
        "COMBAT/SPELL": st.FEED_SPELL,
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
    DEV = os.environ.get("MUTANTS_DEV") == "1"
    logger = logging.getLogger(__name__)

    block_core: List[SegmentLine] = []
    block_ground: List[SegmentLine] = []
    block_monsters: List[SegmentLine] = []
    block_cues: List[SegmentLine] = []

    block_core.append(fmt.format_header(vm["header"]))

    coords = vm["coords"]
    block_core.append(fmt.format_compass(coords["x"], coords["y"]))

    # Directions list should include plain OPEN (base==0) and GATE (base==3) edges.
    # Prefer vm["dirs_open"] if present; otherwise derive from vm["dirs"].
    raw_dirs = vm.get("dirs", {}) or {}
    dirs_open = vm.get("dirs_open")
    if dirs_open is None:
        dirs_open = {
            k: v for k, v in raw_dirs.items() if v and v.get("base", 0) in (0, 3)
        }

    # Validate with the passability engine.
    # - base==0 (open): drop if resolver blocks.
    # - base==3 (gate): never drop; render open/closed/locked via resolver outcome.
    ctx = appctx.current_context() if hasattr(appctx, "current_context") else None
    player_state_hint = ctx.get("player_state") if ctx else None
    world = ctx.get("world") if ctx else None
    dyn_mod = ctx.get("dynamics") if ctx and ctx.get("dynamics") else dyn
    player_display_name = pstate.get_player_display_name(player_state_hint)

    for d in c.DIR_ORDER:
        edge = dirs_open.get(d)
        if not edge:
            continue
        base = edge.get("base", 0)
        try:
            if player_state_hint is not None and world is not None:
                year = getattr(player_state_hint, "year")
                x = getattr(player_state_hint, "x")
                y = getattr(player_state_hint, "y")
                dec = ER.resolve(world, dyn_mod, year, x, y, d, actor={})
                if base == 0:
                    if not dec.passable:
                        if DEV:
                            assert False, f"ui: resolver blocked {d} at ({x},{y})"
                        else:
                            logger.warning(
                                "ui: dropped dir %s (blocked) cur=%r nbr=%r",
                                d,
                                dec.cur_raw,
                                dec.nbr_raw,
                            )
                        continue
                elif base == 3:
                    edge = dict(edge)
                    if edge.get("gate_state", 0) != 2:
                        edge["gate_state"] = 0 if dec.passable else 1
                else:
                    continue
            else:
                if base not in (0, 3):
                    continue
        except Exception:
            if base != 0:
                continue
        block_core.append(fmt.format_direction_segments(d, edge))

    # ---- Ground Block (optional) ----
    has_ground = bool(vm.get("has_ground", False))
    ground_ids = vm.get("ground_item_ids") or []
    if has_ground:
        if not ground_ids:
            if DEV:
                assert False, "ui: has_ground=True but ground_item_ids is empty"
            else:
                logger.warning(
                    "ui: dropping empty ground block (has_ground=True, no items)"
                )
        else:
            block_ground.append(fmt.format_ground_label())
            names = [
                idisp.canonical_name(t if isinstance(t, str) else str(t))
                for t in ground_ids
            ]
            numbered = idisp.number_duplicates(names)
            display = [
                harden_final_display(idisp.with_article(n))
                for n in numbered
            ]
            if is_ui_trace_enabled():
                raw = "On the ground lies: " + ", ".join(display) + "."
            wrapped_lines = wrap_list(display, width)
            if is_ui_trace_enabled():
                from ..app.context import current_context

                ctx = current_context()
                fb = ctx.get("feedback_bus") if ctx else None
                if fb:
                    fb.push(
                        "SYSTEM/INFO",
                        f'UI/GROUND raw={json.dumps(raw, ensure_ascii=False)}',
                    )
                    fb.push(
                        "SYSTEM/INFO",
                        f'UI/GROUND wrap width={width} '
                        f'opts={json.dumps(WRAP_DEBUG_OPTS, sort_keys=True)} '
                        f'lines={json.dumps(wrapped_lines, ensure_ascii=False)}',
                    )
            for line in wrapped_lines:
                block_ground.append(fmt.format_item(line))

    # ---- Monsters block (optional, after Ground) ----
    monster_segments, _ = _render_monsters(vm)
    block_monsters.extend(monster_segments)

    # ---- Cues block (optional, after Monsters) ----
    sep_line: SegmentLine = [("", UC.SEPARATOR_LINE)]
    cues = vm.get("cues_lines") or []
    if cues:
        for idx, cue in enumerate(cues):
            text = str(cue).rstrip()
            block_cues.append([("", text)])
            if idx < len(cues) - 1:
                block_cues.append(list(sep_line))

    # ---- Join blocks with separators between non-empty blocks only ----
    def _join_with_separators(blocks: List[List[SegmentLine]]) -> List[SegmentLine]:
        out: List[SegmentLine] = []
        first = True
        for block in blocks:
            if not block:
                continue
            if not first:
                out.append(list(sep_line))
            out.extend(block)
            first = False
        return out

    def _is_separator(line: SegmentLine) -> bool:
        return len(line) == 1 and line[0][0] == "" and line[0][1] == UC.SEPARATOR_LINE

    def _assert_no_sep_violations(out_lines: List[SegmentLine]) -> List[SegmentLine]:
        if not out_lines:
            return out_lines
        while out_lines and _is_separator(out_lines[0]):
            if DEV:
                assert False, "ui: separator at frame boundary"
            out_lines.pop(0)
        while out_lines and _is_separator(out_lines[-1]):
            if DEV:
                assert False, "ui: separator at frame boundary"
            out_lines.pop()
        i = 1
        while i < len(out_lines):
            if _is_separator(out_lines[i]) and _is_separator(out_lines[i - 1]):
                if DEV:
                    assert False, "ui: consecutive separators"
                out_lines.pop(i)
            else:
                i += 1
        return out_lines

    blocks = [block_core, block_ground, block_monsters, block_cues]
    lines = _join_with_separators(blocks)
    lines = _assert_no_sep_violations(lines)

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
            enriched = _with_player_display_name(ev, player_display_name)
            if isinstance(enriched, Mapping):
                token = _feedback_token(str(enriched.get("kind", "")))
                text = resolve_feedback_text(enriched)
            else:
                token = _feedback_token("")
                text = resolve_feedback_text(ev)
            lines.append([(token, text)])

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
    ctx = appctx.current_context() if hasattr(appctx, "current_context") else None
    player_state_hint = ctx.get("player_state") if ctx else None
    world = ctx.get("world") if ctx else None
    dyn_mod = ctx.get("dynamics") if ctx and ctx.get("dynamics") else dyn
    player_display_name = pstate.get_player_display_name(player_state_hint)

    lines: List[str] = []
    header = vm.get("header")
    if header:
        lines.append(fmt.format_room_title(header))

    coords = vm.get("coords", {})
    compass_str = f"Compass: ({coords.get('x',0)}E : {coords.get('y',0)}N)"
    vm_local = {"compass_str": compass_str}
    lines.append(fmt.format_compass_line(vm_local))

    # Directions list should include plain OPEN (base==0) and GATE (base==3) edges.
    raw_dirs = vm.get("dirs", {}) or {}
    dirs_open = vm.get("dirs_open")
    if dirs_open is None:
        dirs_open = {
            k: v for k, v in raw_dirs.items() if v and v.get("base", 0) in (0, 3)
        }

    DEV = os.environ.get("MUTANTS_DEV") == "1"
    logger = logging.getLogger(__name__)

    # Validate with the passability engine.
    # - base==0 (open): drop if resolver blocks.
    # - base==3 (gate): never drop; show open/closed/locked via resolver.
    for d in c.DIR_ORDER:
        edge = dirs_open.get(d)
        if not edge:
            continue
        base = edge.get("base", 0)
        try:
            if player_state_hint is not None and world is not None:
                year = getattr(player_state_hint, "year")
                x = getattr(player_state_hint, "x")
                y = getattr(player_state_hint, "y")
                dec = ER.resolve(world, dyn_mod, year, x, y, d, actor={})
                if base == 0:
                    if not dec.passable:
                        if DEV:
                            assert False, f"ui: resolver blocked {d} at ({x},{y})"
                        else:
                            logger.warning(
                                "ui: dropped dir %s (blocked) cur=%r nbr=%r",
                                d,
                                dec.cur_raw,
                                dec.nbr_raw,
                            )
                        continue
                elif base == 3:
                    edge = dict(edge)
                    if edge.get("gate_state", 0) != 2:
                        edge["gate_state"] = 0 if dec.passable else 1
                else:
                    continue
            else:
                if base not in (0, 3):
                    continue
        except Exception:
            if base != 0:
                continue
        lines.append(fmt.format_direction_line(d, edge))

    # ------- Build blocks instead of emitting separators inline -------
    block_core = list(lines)
    lines = []

    # ---- Ground Block (optional) ----
    block_ground: list[str] = []
    has_ground = bool(vm.get("has_ground", False))
    ground_ids = vm.get("ground_item_ids") or []
    if has_ground:
        if not ground_ids:
            if DEV:
                assert False, "ui: has_ground=True but ground_item_ids is empty"
            else:
                logger.warning(
                    "ui: dropping empty ground block (has_ground=True, no items)"
                )
        else:
            block_ground.append(fmt.format_ground_header())
            for ln in fmt.format_ground_items(ground_ids):
                block_ground.append(ln)

    # ---- Monsters block (optional, after Ground) ----
    block_monsters: list[str] = []
    _, monsters_logged = _render_monsters(vm)
    if monsters_logged:
        mline = fmt.format_monsters_here(monsters_logged)
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
            enriched = _with_player_display_name(ev, player_display_name)
            if isinstance(enriched, Mapping):
                lines.append(resolve_feedback_text(enriched))
            else:
                lines.append(resolve_feedback_text(ev))

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
