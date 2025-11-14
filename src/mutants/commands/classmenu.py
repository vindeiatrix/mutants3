from __future__ import annotations

from typing import Any

from mutants.services import player_state as pstate
from mutants.services.turn_scheduler import checkpoint
from mutants.ui.class_menu import render_menu


def open_menu(ctx: dict[str, Any]) -> None:
    # Flush any pending runtime changes so the menu reflects canonical saves.
    checkpoint(ctx)
    try:
        canonical_state = pstate.load_state()
    except Exception:
        canonical_state = None
    else:
        if isinstance(ctx, dict) and isinstance(canonical_state, dict):
            ctx["player_state"] = canonical_state

    ctx["mode"] = "class_select"
    # Clear any pending room render while showing the menu
    ctx["render_next"] = False
    render_menu(ctx)


def register(dispatch, ctx) -> None:
    # Real command name (>=3 chars) + single-letter alias 'x'
    dispatch.register("menu", lambda arg: open_menu(ctx))
    dispatch.alias("x", "menu")
