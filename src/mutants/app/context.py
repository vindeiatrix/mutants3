from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, MutableMapping
import time
from datetime import datetime
from pathlib import Path

import logging
import os

from mutants.bootstrap.lazyinit import ensure_player_state
from mutants.bootstrap.runtime import ensure_runtime
from mutants.data.room_headers import ROOM_HEADERS, STORE_FOR_SALE_IDX
from mutants.env import runtime_spawner_config
from mutants.registries import monsters_catalog as mon_catalog
from mutants.registries import monsters_instances as mon_instances
from mutants.registries import world as world_registry
from mutants.registries.world import load_nearest_year
from mutants.state import state_path
from mutants.world import vision
from mutants.ui import renderer
from mutants.ui.textutils import resolve_feedback_text
import sys
from mutants.debug.turnlog import TurnObserver
from mutants.debug import items_probe
from mutants.ui.feedback import FeedbackBus
from mutants.ui.logsink import LogSink
from mutants.ui.themes import load_theme
from mutants.ui import styles as st
from ..registries import items_instances as itemsreg
from mutants.services import (
    audio_cues,
    monster_leveling,
    monsters_state,
    player_state as pstate,
)
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
    if isinstance(state, MutableMapping):
        state = pstate.ensure_class_profiles(state)
    if isinstance(state, dict):
        pstate.normalize_player_state_inplace(state)
        try:
            if pstate._repair_from_templates(state):  # type: ignore[attr-defined]
                pstate.save_state(state, reason="ctx-repair-templates")
        except Exception:
            LOG.debug("Failed to repair player state in context build", exc_info=True)

    active_player = None
    active_class = None
    if isinstance(state, Mapping):
        players = state.get("players")
        active_id = state.get("active_id")
        if isinstance(players, list):
            for entry in players:
                if not isinstance(entry, Mapping):
                    continue
                if active_id is not None and entry.get("id") == active_id:
                    active_player = entry
                    break
            if active_player is None and players:
                candidate = players[0]
                active_player = candidate if isinstance(candidate, Mapping) else None

        if isinstance(active_player, Mapping):
            active_class = active_player.get("class") or active_player.get("name")
            pos = active_player.get("pos") or active_player.get("position")
            if pos is not None:
                state["pos"] = list(pos)
                state["position"] = list(pos)

    if not active_class:
        candidate = state.get("class") if isinstance(state, dict) else None
        if isinstance(candidate, str) and candidate:
            active_class = candidate
    if isinstance(state, MutableMapping) and active_class:
        state["class"] = active_class
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
    # Disable ANSI when running under pytest to keep test expectations simple.
    if os.getenv("PYTEST_CURRENT_TEST"):
        st.set_ansi_enabled(False)
    else:
        st.set_ansi_enabled(theme.ansi_enabled)
    sink = LogSink()
    monsters = monsters_state.load_state()
    spawner = None
    try:
        instances = mon_instances.load_monsters_instances()
        try:
            catalog = mon_catalog.load_monsters_catalog()
        except FileNotFoundError:
            catalog = None
        except Exception:
            catalog = None
        years = world_registry.list_years()
        config_values = runtime_spawner_config()
        spawner = monster_spawner.build_runtime_spawner(
            templates_state=monsters,
            catalog=catalog,
            instances=instances,
            world_loader=world_registry.load_year,
            years=years,
            monsters_state_obj=monsters,
            config=config_values,
        )
    except Exception:
        spawner = None
    bus.subscribe(sink.handle)
    turn_observer = TurnObserver()
    monster_leveling.attach(bus, monsters)
    ctx: Dict[str, Any] = {
        "player_state": state,
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
        "render_next": False,
        "peek_vm": None,
        "session": {"active_class": active_class} if active_class else {},
    }
    if isinstance(state, Mapping):
        canonical_pos = pstate.canonical_player_pos(state)
        pstate.sync_runtime_position(ctx, canonical_pos)
    if spawner is not None:
        ctx["monster_spawner"] = spawner
        services_entry = ctx.setdefault("services", {})
        if isinstance(services_entry, dict):
            services_entry["monster_spawner"] = spawner
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


def build_room_vm(
    state: Dict[str, Any],
    world_loader: Any,
    headers: Iterable[str],
    monsters: Any | None = None,
    items: Any | None = None,
) -> Dict[str, Any]:
    """Build a room view model for the active player."""
    year, x, y = pstate.canonical_player_pos(state)
    player_pos = (year, x, y)
    pos = [year, x, y]

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
    seen_monster_ids: set[str] = set()

    # Always use the authoritative cache unless a specific source is supplied.
    monsters_source = monsters
    if monsters_source is None:
        ctx = current_context()
        if isinstance(ctx, Mapping):
            monsters_source = ctx.get("monsters")

    mons_iter: List[Any] = []
    if monsters_source:
        try:
            mons_iter = list(monsters_source.list_at(year, x, y))  # type: ignore[attr-defined]
        except Exception:
            LOG.warning(
                "[build_room_vm] monsters_source=%s list_at raised",
                type(monsters_source).__name__,
                exc_info=True,
            )
            mons_iter = []
        else:
            ids_logged: List[Any] = []
            bad_entries: List[Any] = []
            for entry in mons_iter:
                if isinstance(entry, Mapping):
                    ident = entry.get("instance_id") or entry.get("id")
                    ids_logged.append(str(ident) if ident is not None else None)
                    inst_id = entry.get("instance_id")
                else:
                    ids_logged.append(None)
                    inst_id = getattr(entry, "instance_id", None)
                if not isinstance(inst_id, str) or not inst_id.startswith("i."):
                    bad_entries.append(entry)
            LOG.warning(
                "[build_room_vm] monsters_source=%s returned %d rows ids=%s",
                type(monsters_source).__name__,
                len(mons_iter),
                ids_logged,
            )
            if bad_entries:
                try:
                    bad_ids = []
                    for entry in bad_entries:
                        if isinstance(entry, Mapping):
                            bad_ids.append(entry.get("instance_id"))
                        else:
                            bad_ids.append(getattr(entry, "instance_id", None))
                except Exception:
                    bad_ids = ["<unprintable>"]
                LOG.warning(
                    "[build_room_vm] non-instance-shaped monster ids at %s,%s,%s: %s",
                    year,
                    x,
                    y,
                    bad_ids,
                )

    for m in mons_iter:
        if not isinstance(m, Mapping):
            continue
        name = m.get("name") or m.get("monster_id", "?")
        raw_id = m.get("id") or m.get("instance_id") or m.get("monster_id")
        mid = str(raw_id) if raw_id else ""
        if mid and mid in seen_monster_ids:
            continue
        if mid:
            seen_monster_ids.add(mid)
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

    # Preserve the ready target even when the monster moves away from the player.
    # Combat commands will validate proximity as needed.

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


def _log_move_lag(ctx: Dict[str, Any], probe: Mapping[str, Any]) -> None:
    """Append a movement lag entry to state/logs/move_lag.log (independent of global logging)."""
    start = probe.get("start")
    if not isinstance(start, (float, int)):
        return
    try:
        duration_ms = (time.perf_counter() - float(start)) * 1000.0
    except Exception:
        return
    try:
        log_dir = state_path("logs")
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(log_dir) / "move_lag.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        dir_token = probe.get("dir") or "?"
        from_pos = probe.get("from") or ()
        try:
            year, fx, fy = from_pos
        except Exception:
            year, fx, fy = ("?", "?", "?")
        pos = pstate.canonical_player_pos(ctx.get("player_state")) if ctx.get("player_state") else ("?", "?", "?")
        mon_obj = ctx.get("monsters")
        total_monsters = None
        monsters_in_year = None
        try:
            if mon_obj is not None and hasattr(mon_obj, "list_all"):
                total_monsters = len(mon_obj.list_all())  # type: ignore[arg-type]
            if mon_obj is not None and hasattr(mon_obj, "list_in_year") and not isinstance(year, str):
                monsters_in_year = len(mon_obj.list_in_year(int(year)))  # type: ignore[arg-type]
        except Exception:
            total_monsters = total_monsters
        line = (
            f"{now} dir={dir_token} from=({year},{fx},{fy}) to=({pos[0]},{pos[1]},{pos[2]}) "
            f"lag_ms={duration_ms:.2f}"
        )
        if total_monsters is not None:
            line += f" total_monsters={total_monsters}"
        if monsters_in_year is not None:
            line += f" year_monsters={monsters_in_year}"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # Best-effort; never raise from logging.
        pass


def render_frame(ctx: Dict[str, Any]) -> None:
    vm = ctx.pop("peek_vm", None)
    is_peek = vm is not None
    if vm is None:
        # Cache is the single read path for monsters; never read directly from the store.
        vm = build_room_vm(
            ctx["player_state"],
            ctx["world_loader"],
            ctx["headers"],
            ctx["monsters"],
            ctx.get("items"),
        )
    force_show_monsters = bool(ctx.pop("_force_show_monsters", False))
    if is_peek:
        # Peeking into adjacent tiles should never emit shadows; show the tile as-is.
        vm = dict(vm)
        vm["shadows"] = []
        force_show_monsters = True
    # Allow one-frame suppression of monster presence (e.g., immediately after an arrival cue).
    if (not force_show_monsters) and ctx.pop("_suppress_monsters_once", False):
        vm = dict(vm)
        vm["monsters_here"] = []
    # Allow one-frame suppression of shadow cues (e.g., immediately after a flee leave).
    if ctx.pop("_suppress_shadows_once", False):
        vm = dict(vm)
        vm["shadows"] = []
    shadow_hint = ctx.pop("_shadow_hint_once", None)
    if shadow_hint:
        vm = dict(vm)
        vm["shadows"] = list(shadow_hint)
    cues = audio_cues.drain(ctx)
    events = ctx["feedback_bus"].drain()
    if cues:
        cue_events = [{"text": c} for c in cues]
        events.extend(cue_events)
    # Process system/arrival cues after movement audio by reordering so arrival comes last.
    if events:
        arrivals = [ev for ev in events if isinstance(ev, Mapping) and ev.get("kind") == "COMBAT/INFO" and "arrived from" in str(ev.get("text", ""))]
        others = [ev for ev in events if ev not in arrivals]
        events = others + arrivals
    lines = ctx["renderer"](
        vm,
        feedback_events=events,
        palette=ctx["theme"].palette,
        width=ctx["theme"].width,
    )
    # Expose vm for tests that inspect rendered payloads.
    if isinstance(ctx, MutableMapping):
        ctx["_last_vm"] = vm
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
    # Movement lag probe: compute render latency if a move set a probe.
    probe = ctx.pop("_move_lag_probe", None)
    if isinstance(probe, Mapping):
        _log_move_lag(ctx, probe)


def flush_feedback(ctx: Dict[str, Any]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    events = ctx["feedback_bus"].drain()
    if not events:
        return
    palette = ctx["theme"].palette
    in_class_menu = ctx.get("mode") == "class_select"
    last_was_kill_info = False
    for ev in events:
        kind = ev.get("kind", "") if isinstance(ev, Mapping) else ""
        group = renderer._feedback_group(str(kind)) if hasattr(renderer, "_feedback_group") else None
        if group:
            text = resolve_feedback_text(ev)
            if text == "":
                print("")
                continue
            is_kill_info = text.startswith("You have slain") or text.startswith(
                "Your experience points"
            ) or text.startswith("You collect ")
            if not in_class_menu:
                if not (is_kill_info and last_was_kill_info):
                    print("***")
            print(st.colorize_text(text, group=group))
            last_was_kill_info = is_kill_info
            if not is_kill_info:
                last_was_kill_info = False
        else:
            token = renderer._feedback_token(str(kind))
            text = resolve_feedback_text(ev)
            if text == "":
                print("")
                continue
            if not in_class_menu:
                print("***")
            print(st.resolve_segments([(token, text)], palette))
            last_was_kill_info = False
