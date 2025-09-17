from __future__ import annotations

from typing import Any

from mutants.ui.class_menu import render_menu


def open_menu(ctx: dict[str, Any]) -> None:
    ctx["mode"] = "class_select"
    render_menu(ctx)


def register(dispatch, ctx) -> None:
    """Register the class menu command bindings."""

    dispatch.register("x", lambda arg: open_menu(ctx))
