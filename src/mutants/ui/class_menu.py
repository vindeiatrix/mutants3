from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from mutants.constants import CLASS_ORDER
from mutants.services import player_state as pstate
from mutants.services import player_reset
from mutants.engine import session


ROW_FMT = "{idx:>2}. Mutant {cls:<7}  Level: {lvl:<2}  Year: {yr:<4}  ({x:>2} {y:>2})"


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
        return pstate.ensure_class_profiles(state)
    return {"players": [], "active_id": None}


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
    state = _load_canonical_state()
    players_by_class = _players_by_class(state)
    bus = ctx["feedback_bus"]
    for i, class_name in enumerate(CLASS_ORDER, start=1):
        player = players_by_class.get(class_name, {})
        yr, x, y = _coerce_pos(player)
        lvl = int(player.get("level", 1) or 1)
        bus.push(
            "SYSTEM/OK",
            ROW_FMT.format(idx=i, cls=class_name, lvl=lvl, yr=yr, x=x, y=y),
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
    state_hint = ctx.get("player_state") if isinstance(ctx, dict) else None
    state = (
        pstate.ensure_class_profiles(state_hint)
        if isinstance(state_hint, dict)
        else _load_canonical_state()
    )
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
        raise SystemExit(0)
    if lowered.startswith("bury"):
        parts = lowered.split()
        if len(parts) != 2 or not parts[1].isdigit():
            bus.push("SYSTEM/ERROR", "Usage: BURY [class number]")
            return
        idx_n = int(parts[1])
        if not (1 <= idx_n <= slot_count):
            bus.push("SYSTEM/ERROR", f"Choose a number 1–{slot_count}")
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
            f"Please enter a number (1–{slot_count}), 'bury <n>', or '?'.",
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

    active_player = next(
        (p for p in updated_state.get("players", []) if p.get("id") == target_id), None
    )
    resolved_class = pstate.get_active_class(updated_state)
    active_pos = updated_state.get("pos") or [2000, 0, 0]
    if isinstance(active_player, dict):
        resolved_class = active_player.get("class") or resolved_class
        active_pos = active_player.get("pos") or active_pos

    pstate.sync_runtime_position(ctx, active_pos)

    session.set_active_class(resolved_class)
    session_ctx = ctx.setdefault("session", {})
    if isinstance(session_ctx, dict):
        session_ctx["active_class"] = resolved_class
    ctx["player_state"] = updated_state
    ctx["mode"] = None
    ctx["render_next"] = True
