from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

import logging

from mutants.constants import CLASS_ORDER
from mutants.engine import session
from mutants.services import player_reset, player_state as pstate

LOG = logging.getLogger(__name__)


ROW_FMT = "{idx:>2}. Mutant {cls:<7}  Level: {lvl:<2}  Year: {yr:<4}  ({x} {y})"


def _coerce_pos(player) -> Tuple[int, int, int]:
    pos = player.get("pos") or [2000, 0, 0]
    try:
        yr = int(pos[0])
        x = int(pos[1])
        y = int(pos[2])
        return (yr, x, y)
    except Exception:
        return (2000, 0, 0)


def _load_canonical_state() -> Dict[str, Any]:
    """Return a fresh, canonical player state from disk."""

    state = pstate.load_state()
    if isinstance(state, Mapping):
        state = dict(state)
    if isinstance(state, dict):
        hydrated = pstate.ensure_class_profiles(state)
        if isinstance(hydrated, dict):
            pstate.normalize_player_state_inplace(hydrated)
            return hydrated
    return {"players": [], "active_id": None}


def _state_from_ctx(ctx: Mapping[str, Any] | None) -> Dict[str, Any]:
    state = _load_canonical_state()
    ensured = pstate.ensure_class_profiles(state)
    if isinstance(ensured, dict):
        pstate.normalize_player_state_inplace(ensured)
        state = ensured
    if isinstance(ctx, dict):
        ctx["player_state"] = state
    return state


def _players_by_class(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    players = state.get("players")
    if not isinstance(players, list):
        return mapping
    for entry in players:
        if not isinstance(entry, dict):
            continue
        cls_token = pstate.normalize_class_name(entry.get("class")) or pstate.normalize_class_name(
            entry.get("name")
        )
        if cls_token:
            mapping[cls_token] = entry
    return mapping


def render_menu(ctx: dict) -> None:
    state = _state_from_ctx(ctx)
    players_by_class = _players_by_class(state)
    bus = ctx["feedback_bus"]
    for i, class_name in enumerate(CLASS_ORDER, start=1):
        player = players_by_class.get(class_name, {})
        yr, x, y = _coerce_pos(player)
        xs = str(int(x))
        ys = str(int(y))
        lvl = int(player.get("level", 1) or 1)
        bus.push(
            "SYSTEM/OK",
            ROW_FMT.format(idx=i, cls=class_name, lvl=lvl, yr=yr, x=xs, y=ys),
        )
    # Blank line between the list and the hint line.
    bus.push("SYSTEM/OK", "")
    bus.push(
        "SYSTEM/OK",
        "Type BURY [class number] to reset a player. Type X to exit.",
    )
    bus.push("SYSTEM/OK", "***")


def _select_index(value: str, max_n: int) -> int | None:
    value = value.strip()
    if not value.isdigit():
        return None
    selected = int(value)
    return selected if 1 <= selected <= max_n else None


def handle_input(raw: str, ctx: dict) -> None:
    s = (raw or "").strip()
    state = _state_from_ctx(ctx)
    players = state.get("players", [])
    players_by_class = _players_by_class(state)
    slot_count = len(CLASS_ORDER)
    bus = ctx["feedback_bus"]
    if not s:
        return
    lowered = s.lower()
    if lowered == "?":
        bus.push(
            "SYSTEM/INFO",
            "Select a class by number. Type BURY [class number] to reset a player. Type X to exit.",
        )
        return
    if lowered == "x":
        try:
            pstate.clear_target(reason="quit-from-class-menu")
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("Failed to clear ready target when quitting from class menu")
        raise SystemExit(0)
    if lowered.startswith("bury"):
        parts = lowered.split()
        if len(parts) != 2:
            bus.push("SYSTEM/ERROR", "Usage: BURY [class number]")
            return
        if parts[1] == "all":
            player_reset.bury_all()
            ctx["player_state"] = _load_canonical_state()
            bus.push("SYSTEM/OK", "Player reset.")
            render_menu(ctx)
            return
        if not parts[1].isdigit():
            bus.push("SYSTEM/ERROR", "Usage: BURY [class number]")
            return
        idx_n = int(parts[1])
        if not (1 <= idx_n <= slot_count):
            bus.push("SYSTEM/ERROR", f"Choose a number 1-{slot_count}")
            return
        player_reset.bury_by_index(idx_n - 1)
        ctx["player_state"] = _load_canonical_state()
        bus.push("SYSTEM/OK", "Player reset.")
        render_menu(ctx)
        return
    idx = _select_index(lowered, slot_count)
    if idx is None:
        bus.push(
            "SYSTEM/ERROR",
            f"Please enter a number (1-{slot_count}), 'bury <n>', or '?'.",
        )
        return
    class_name = CLASS_ORDER[idx - 1]
    selected_player = players_by_class.get(class_name)
    if not isinstance(selected_player, dict):
        bus.push("SYSTEM/ERROR", f"No player profile for {class_name}.")
        return
    target_id = selected_player.get("id")
    if not target_id:
        bus.push("SYSTEM/ERROR", "No player id for that slot.")
        return

    try:
        updated_state = pstate.set_active_player(state, str(target_id))
        pstate.save_state(updated_state, reason="change-active-class")
    except Exception:
        bus.push("SYSTEM/ERROR", "Could not activate that player.")
        return

    refreshed_state: Mapping[str, Any] | None
    try:
        refreshed_state = pstate.load_state()
    except Exception:
        refreshed_state = updated_state

    if isinstance(refreshed_state, Mapping) and not isinstance(refreshed_state, dict):
        refreshed_state = dict(refreshed_state)

    if isinstance(refreshed_state, dict):
        pstate.normalize_player_state_inplace(refreshed_state)
        ctx["player_state"] = refreshed_state

    canonical_pos = pstate.canonical_player_pos(ctx.get("player_state"))
    pstate.sync_runtime_position(ctx, canonical_pos)

    resolved_class = pstate.get_active_class(ctx.get("player_state"))
    session.set_active_class(resolved_class)
    session_ctx = ctx.setdefault("session", {})
    if isinstance(session_ctx, dict):
        session_ctx["active_class"] = resolved_class
    ctx["mode"] = None
    ctx["render_next"] = True
