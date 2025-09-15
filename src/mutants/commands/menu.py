"""Commands for switching between menus."""
from __future__ import annotations


def exit_to_selection(arg: str, ctx) -> None:
    state_mgr = ctx.get("state_manager")
    screen_mgr = ctx.get("screen_manager")
    if screen_mgr is None:
        ctx["feedback_bus"].push("SYSTEM/WARN", "Class selection unavailable.")
        return
    if state_mgr is not None:
        state_mgr.persist()
    screen_mgr.enter_selection(ctx)
    ctx["feedback_bus"].push("SYSTEM/OK", "Returned to class selection.")


def register(dispatch, ctx) -> None:
    dispatch.register("exitmenu", lambda arg: exit_to_selection(arg, ctx))
    dispatch.alias("x", "exitmenu")
