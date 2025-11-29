from __future__ import annotations

from typing import Any

import logging

from mutants.services import player_state as pstate
from mutants.ui.class_menu import render_menu


LOG = logging.getLogger(__name__)


def open_menu(ctx: dict[str, Any]) -> None:
    try:
        pstate.clear_target(reason="class-menu")
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to clear ready target when entering class menu")
    ctx["mode"] = "class_select"
    # Clear any pending room render while showing the menu
    ctx["render_next"] = False
    render_menu(ctx)


def register(dispatch, ctx) -> None:
    # Real command name (>=3 chars) + single-letter alias 'x'
    dispatch.register("menu", lambda arg: open_menu(ctx))
    dispatch.alias("x", "menu")
