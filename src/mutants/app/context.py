from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from mutants.bootstrap.lazyinit import ensure_player_state
from mutants.bootstrap.runtime import ensure_runtime
from mutants.data.room_headers import ROOM_HEADERS
from mutants.registries.world import load_year
from mutants.ui import renderer
from mutants.ui.feedback import FeedbackBus
from mutants.ui.logsink import LogSink
from mutants.ui.themes import Theme, load_theme

# Paths
DEFAULT_THEME_PATH = Path("state/ui/themes/bbs.json")


def build_context() -> Dict[str, Any]:
    """Build the application context."""
    info = ensure_runtime()
    state = ensure_player_state()
    cfg = info.get("config", {})
    bus = FeedbackBus()
    theme_path = cfg.get("theme_path", str(DEFAULT_THEME_PATH))
    theme = load_theme(str(theme_path))
    sink = LogSink()
    bus.subscribe(sink.handle)
    ctx: Dict[str, Any] = {
        "player_state": state,
        "world_loader": load_year,
        "monsters": None,
        "items": None,
        "headers": ROOM_HEADERS,
        "feedback_bus": bus,
        "logsink": sink,
        "theme": theme,
        "renderer": renderer.render,
        "config": cfg,
    }
    return ctx


# Backwards compatibility
build = build_context


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
    p = _active(state)
    pos = p.get("pos") or [0, 0, 0]
    year, x, y = pos[0], pos[1], pos[2]
    world = world_loader(year)
    tile = world.get_tile(x, y)

    idx = int(tile.get("header_idx", 0)) if tile else 0
    header = list(headers)[idx] if 0 <= idx < len(list(headers)) else ""

    dirs: Dict[str, Dict[str, Any]] = {}
    if tile:
        for d in ("N", "S", "E", "W"):
            e = tile["edges"].get(d, {})
            dirs[d] = {k: e.get(k) for k in ("base", "gate_state", "key_type")}

    monsters_here: List[Dict[str, str]] = []
    if monsters:
        try:
            for m in monsters.list_at(year, x, y):  # type: ignore[attr-defined]
                name = m.get("name") or m.get("monster_id", "?")
                monsters_here.append({"name": name})
        except Exception:
            pass

    ground_items: List[Dict[str, str]] = []
    if items and hasattr(items, "list_at"):
        try:
            for it in items.list_at(year, x, y):  # type: ignore[attr-defined]
                name = it.get("name") or it.get("item_id", "?")
                ground_items.append({"name": name})
        except Exception:
            pass

    vm: Dict[str, Any] = {
        "header": header,
        "coords": {"x": x, "y": y},
        "dirs": dirs,
        "monsters_here": monsters_here,
        "ground_items": ground_items,
        "events": [],
        "shadows": [],
        "flags": {"dark": bool(tile.get("dark")) if tile else False},
    }
    return vm


def render_frame(ctx: Dict[str, Any]) -> None:
    vm = build_room_vm(
        ctx["player_state"],
        ctx["world_loader"],
        ctx["headers"],
        ctx.get("monsters"),
        ctx.get("items"),
    )
    events = ctx["feedback_bus"].drain()
    lines = ctx["renderer"](
        vm,
        feedback_events=events,
        palette=ctx["theme"].palette,
        width=ctx["theme"].width,
    )
    for line in lines:
        print(line)
