from __future__ import annotations

from typing import Tuple

from mutants.services import player_state as pstate
from mutants.services import player_reset
from mutants.services import player_active as act
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


def render_menu(ctx: dict) -> None:
    state = pstate.load_state()
    players = state.get("players", [])
    bus = ctx["feedback_bus"]
    for i, player in enumerate(players, start=1):
        yr, x, y = _coerce_pos(player)
        lvl = int(player.get("level", 1) or 1)
        cls = str(player.get("class") or "Unknown")
        bus.push(
            "SYSTEM/OK",
            ROW_FMT.format(idx=i, cls=cls, lvl=lvl, yr=yr, x=x, y=y),
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
    state = pstate.load_state()
    players = state.get("players", [])
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
        if not (1 <= idx_n <= len(players)):
            bus.push("SYSTEM/ERROR", f"Choose a number 1–{len(players)}")
            return
        player_reset.bury_by_index(idx_n - 1)
        ctx["player_state"] = pstate.load_state()
        bus.push("SYSTEM/OK", "Player reset.")
        render_menu(ctx)
        return
    idx = _select_index(lowered, len(players))
    if idx is None:
        bus.push(
            "SYSTEM/ERROR",
            f"Please enter a number (1–{len(players)}), 'bury <n>', or '?'.",
        )
        return
    target_id = players[idx - 1].get("id")
    if not target_id:
        bus.push("SYSTEM/ERROR", "No player id for that slot.")
        return
    selected_player = players[idx - 1]
    class_name = str(
        (selected_player.get("class") or selected_player.get("name") or "Thief")
    )
    class_name = class_name.strip()
    if not class_name:
        class_name = "Thief"

    year_val = 2000
    sel_pos = selected_player.get("pos")
    if isinstance(sel_pos, (list, tuple)) and sel_pos:
        try:
            year_val = int(sel_pos[0])
        except Exception:
            year_val = 2000
    if year_val == 2000:
        try:
            year_candidate = int(selected_player.get("year"))
        except Exception:
            year_candidate = None
        if isinstance(year_candidate, int):
            year_val = year_candidate

    new_state = act.set_active(str(target_id))

    session.set_active_class(class_name)
    session_ctx = ctx.setdefault("session", {})
    if isinstance(session_ctx, dict):
        session_ctx["active_class"] = class_name
    ctx["player_state"] = new_state
    ctx["mode"] = None
    ctx["render_next"] = True
