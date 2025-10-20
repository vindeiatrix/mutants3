from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, MutableMapping

import logging
import os
import random

from mutants.bootstrap.lazyinit import ensure_player_state
from mutants.bootstrap.runtime import ensure_runtime
from mutants.data.room_headers import ROOM_HEADERS, STORE_FOR_SALE_IDX
from mutants.registries.world import load_nearest_year
from mutants.state import state_path
from mutants.world import vision
from mutants.ui import renderer
from mutants.ui.textutils import resolve_feedback_text
from mutants.debug.turnlog import TurnObserver
from mutants.debug import items_probe
from mutants.ui.feedback import FeedbackBus
from mutants.ui.logsink import LogSink
from mutants.ui.themes import Theme, load_theme
from mutants.ui import styles as st
from ..registries import items_instances as itemsreg
from mutants.services import (
    audio_cues,
    monster_leveling,
    monsters_state,
    player_state as pstate,
)
from mutants.services.combat_config import CombatConfig, load_combat_config
from mutants.services import monster_actions
from mutants.services.turn_scheduler import TurnScheduler
from mutants.engine import session

LOG = logging.getLogger(__name__)
WORLD_DEBUG = os.getenv("WORLD_DEBUG") == "1"

# --- store-aware header resolution ------------------------------------------
def _store_price(year: int) -> int:
    """
    store_price(year) = 25000 * (1 + (year-2000)/100)
    Examples: 2000→25,000; 2100→50,000.
    """
    return int(25000 * (1 + (int(year) - 2000) / 100.0))


def _resolve_header_text(tile: dict, year: int) -> str:
    """
    Use the store header if and only if store_id is not None; otherwise use
    header_idx from the tile. Substitute {PRICE} for store tiles.
    """
    is_store = tile.get("store_id") is not None
    idx = STORE_FOR_SALE_IDX if is_store else int(tile.get("header_idx", 0))
    text = ROOM_HEADERS[idx] if 0 <= idx < len(ROOM_HEADERS) else ""
    if idx == STORE_FOR_SALE_IDX:
        text = text.replace("{PRICE}", f"{_store_price(year):,}")
    return text
# ---------------------------------------------------------------------------

# Paths
DEFAULT_THEME_PATH = state_path("ui", "themes", "bbs.json")

_CURRENT_CTX: Dict[str, Any] | None = None


def build_context() -> Dict[str, Any]:
    """Build the application context."""
    info = ensure_runtime()
    state = ensure_player_state()
    runtime_state = pstate.PlayerState(state)
    active = state.get("active") if isinstance(state, dict) else None
    active_class = None
    if isinstance(active, dict):
        candidate = active.get("class")
        if isinstance(candidate, str) and candidate:
            active_class = candidate
    if not active_class:
        candidate = state.get("class") if isinstance(state, dict) else None
        if isinstance(candidate, str) and candidate:
            active_class = candidate
    session.set_active_class(active_class)
    cfg = info.get("config", {})
    bus = FeedbackBus()
    theme_path = cfg.get("theme_path", str(DEFAULT_THEME_PATH))
    theme = load_theme(str(theme_path))
    # Apply theme settings to styles (palette path + ANSI toggle)
    if theme.colors_path:
        st.set_colors_map_path(theme.colors_path)
    else:
        st.set_colors_map_path(None)
    st.reload_colors_map()
    st.set_ansi_enabled(theme.ansi_enabled)
    sink = LogSink()
    monsters = monsters_state.load_state()
    bus.subscribe(sink.handle)
    turn_observer = TurnObserver()
    monster_leveling.attach(bus, monsters)
    try:
        combat_cfg = load_combat_config(state_dir=str(state_path()))
    except Exception:
        combat_cfg = CombatConfig()
    ctx: Dict[str, Any] = {
        "player_state": runtime_state,
        # Multi-year aware loader: exact year if present, otherwise closest available.
        "world_loader": load_nearest_year,
        "monsters": monsters,
        "items": itemsreg,
        "headers": ROOM_HEADERS,
        "feedback_bus": bus,
        "logsink": sink,
        "turn_observer": turn_observer,
        "theme": theme,
        "renderer": renderer.render,
        "config": cfg,
        "combat_config": combat_cfg,
        "monster_ai_rng": random.Random(),
        "room_entry_event": "ENTRY",
        "render_next": False,
        "peek_vm": None,
        "session": {"active_class": active_class} if active_class else {},
    }
    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler
    session.set_turn_scheduler(scheduler)
    global _CURRENT_CTX
    _CURRENT_CTX = ctx
    return ctx


# Backwards compatibility
build = build_context


def current_context() -> Dict[str, Any] | None:
    return _CURRENT_CTX


def _active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def _player_position(state: Mapping[str, Any] | None) -> tuple[int, int, int] | None:
    if not isinstance(state, Mapping):
        return None
    try:
        player = _active(state)  # type: ignore[arg-type]
    except Exception:
        player = state.get("active") if isinstance(state.get("active"), Mapping) else None
    if not isinstance(player, Mapping):
        return None
    pos = player.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            year, x, y = int(pos[0]), int(pos[1]), int(pos[2])
            return year, x, y
        except (TypeError, ValueError):
            return None
    return None


def build_room_vm(
    state: Dict[str, Any],
    world_loader: Any,
    headers: Iterable[str],
    monsters: Any | None = None,
    items: Any | None = None,
) -> Dict[str, Any]:
    """Build a room view model for the active player."""
    p = _active(state)
    pos = p.get("pos") or [0, 0, 0]
    year, x, y = pos[0], pos[1], pos[2]
    player_pos = (year, x, y)

    if WORLD_DEBUG:
        LOG.debug(
            "[room] build_room_vm pos=%s (year=%s,x=%s,y=%s)",
            pos, year, x, y
        )
    world = world_loader(year)
    tile = world.get_tile(x, y)

    header = _resolve_header_text(tile or {}, year)

    dirs: Dict[str, Dict[str, Any]] = {}
    if tile:
        for d in ("N", "S", "E", "W"):
            e = tile["edges"].get(d, {})
            dirs[d] = {k: e.get(k) for k in ("base", "gate_state", "key_type")}

    monsters_here: List[Dict[str, str]] = []
    monster_ids: set[str] = set()
    if monsters:
        try:
            for m in monsters.list_at(year, x, y):  # type: ignore[attr-defined]
                name = m.get("name") or m.get("monster_id", "?")
                raw_id = m.get("id") or m.get("instance_id") or m.get("monster_id")
                mid = str(raw_id) if raw_id else ""
                hp_block = m.get("hp") if isinstance(m, Mapping) else None
                is_alive = True
                if isinstance(hp_block, Mapping):
                    try:
                        is_alive = int(hp_block.get("current", 0)) > 0
                    except (TypeError, ValueError):
                        is_alive = True
                entry: Dict[str, str] = {"name": name}
                if mid:
                    entry["id"] = mid
                monsters_here.append(entry)
                if mid and is_alive:
                    monster_ids.add(mid)
        except Exception:
            monster_ids.clear()
    try:
        pstate.ensure_active_ready_target_in(monster_ids, reason="tile-mismatch")
    except Exception:
        pass

    ground_ids: List[str] = []
    if items and hasattr(items, "list_ids_at"):
        try:
            ground_ids = items.list_ids_at(year, x, y)  # type: ignore[attr-defined]
            # Emit a renderer-side probe of exactly what we're about to show.
            try:
                items_probe.probe("renderer", items, year, x, y)
                items_probe.dump_tile_instances(items, year, x, y, tag="renderer-dump")
            except Exception:
                pass
        except Exception:
            ground_ids = []

    shadows = vision.adjacent_monster_directions(monsters, player_pos)

    vm: Dict[str, Any] = {
        "header": header,
        "coords": {"x": x, "y": y},
        "dirs": dirs,
        "monsters_here": monsters_here,
        "ground_item_ids": ground_ids,
        "has_ground": bool(ground_ids),
        "events": [],
        "shadows": shadows,
        "flags": {"dark": bool(tile.get("dark")) if tile else False},
    }
    return vm


def _process_room_entry(ctx: Dict[str, Any], event: str) -> None:
    monsters = ctx.get("monsters")
    if not monsters or not hasattr(monsters, "list_at"):
        return
    state = ctx.get("player_state")
    pos = _player_position(state if isinstance(state, Mapping) else None)
    if pos is None:
        return
    year, x, y = pos
    try:
        monsters_here = list(monsters.list_at(year, x, y))  # type: ignore[attr-defined]
    except Exception:
        return

    if not monsters_here:
        return

    rng = ctx.get("monster_ai_rng")
    if not isinstance(rng, random.Random):
        rng = random.Random()
        ctx["monster_ai_rng"] = rng

    config = ctx.get("combat_config")
    config_obj = config if isinstance(config, CombatConfig) else None
    bus = ctx.get("feedback_bus")
    dirty = False

    for monster in monsters_here:
        target_monster: MutableMapping[str, Any] | None = monster if isinstance(monster, MutableMapping) else None
        monster_id: str | None = None
        if isinstance(monster, Mapping):
            raw_id = monster.get("id") or monster.get("instance_id") or monster.get("monster_id")
            if raw_id is not None:
                monster_id = str(raw_id)
        if monster_id and hasattr(monsters, "get"):
            try:
                lookup = monsters.get(monster_id)  # type: ignore[attr-defined]
            except Exception:
                lookup = None
            if isinstance(lookup, MutableMapping):
                target_monster = lookup
        if target_monster is None:
            continue
        outcome = monster_actions.roll_entry_target(
            target_monster,
            state if isinstance(state, Mapping) else None,
            rng,
            config=config_obj,
            bus=bus,
            event=event,
        )
        if outcome.get("target_set"):
            dirty = True

    if dirty and hasattr(monsters, "mark_dirty"):
        try:
            monsters.mark_dirty()  # type: ignore[attr-defined]
        except Exception:
            pass


def render_frame(ctx: Dict[str, Any]) -> None:
    vm = ctx.pop("peek_vm", None)
    if vm is None:
        event = ctx.pop("room_entry_event", "ENTRY")
        try:
            _process_room_entry(ctx, event)
        except Exception:
            pass
        vm = build_room_vm(
            ctx["player_state"],
            ctx["world_loader"],
            ctx["headers"],
            ctx.get("monsters"),
            ctx.get("items"),
        )
    else:
        ctx.pop("room_entry_event", None)
    cues = audio_cues.drain(ctx)
    if cues:
        vm = dict(vm)
        existing = list(vm.get("cues_lines") or [])
        existing.extend(cues)
        vm["cues_lines"] = existing

    events = ctx["feedback_bus"].drain()
    lines = ctx["renderer"](
        vm,
        feedback_events=events,
        palette=ctx["theme"].palette,
        width=ctx["theme"].width,
    )
    for line in lines:
        print(line)
    # Also log the human-facing ground list that was rendered.
    try:
        if items_probe.enabled():
            items_probe.setup_file_logging()
            gids = vm.get("ground_item_ids") or []
            logging.getLogger("mutants.itemsdbg").info(
                "[itemsdbg] renderer_shown ground_ids=%s", gids
            )
    except Exception:
        pass


def flush_feedback(ctx: Dict[str, Any]) -> None:
    events = ctx["feedback_bus"].drain()
    if not events:
        return
    palette = ctx["theme"].palette
    for ev in events:
        token = renderer._feedback_token(ev.get("kind", ""))
        line = st.resolve_segments([(token, resolve_feedback_text(ev))], palette)
        print(line)
