from __future__ import annotations

from typing import Any

from mutants.services import player_state as pstate
from mutants.ui.class_menu import render_menu


def open_menu(ctx: dict[str, Any]) -> None:
    pstate.set_runtime_combat_target(ctx.get("player_state"), None)
    ctx["mode"] = "class_select"
    # Clear any pending room render while showing the menu
    ctx["render_next"] = False
    render_menu(ctx)


def register(dispatch, ctx) -> None:
    # Real command name (>=3 chars) + single-letter alias 'x'
    dispatch.register("menu", lambda arg: open_menu(ctx))
    dispatch.alias("x", "menu")
