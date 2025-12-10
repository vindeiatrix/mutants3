from __future__ import annotations
import logging

from mutants.app.context import build_context, render_frame, flush_feedback
from mutants.repl.dispatch import Dispatch
from mutants.commands.register_all import register_all
from mutants.repl.prompt import make_prompt
from mutants.repl.help import startup_banner
from mutants.ui.class_menu import handle_input, render_menu
from mutants.services import player_state as pstate


LOG = logging.getLogger(__name__)


def _clear_target_on_exit(reason: str = "shutdown") -> None:
    try:
        pstate.clear_target(reason=reason)
    except Exception:  # pragma: no cover - defensive guard
        LOG.exception("Failed to clear ready target during shutdown")


def main() -> None:
    ctx = build_context()
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    dispatch.set_context(ctx)

    # Auto-register all commands in mutants.commands
    register_all(dispatch, ctx)

    # Show startup banner *before* entering menu
    ctx["feedback_bus"].push("SYSTEM/INFO", startup_banner(ctx))

    # Enter class selection menu at startup; suppress any pending room render.
    try:
        monsters_obj = ctx.get("monsters")
        from mutants.services import monsters_state

        monsters_state.clear_all_targets(monsters_obj)
    except Exception:  # pragma: no cover - best effort
        LOG.debug("Failed to clear monster targets on startup", exc_info=True)
    ctx["mode"] = "class_select"
    ctx["render_next"] = False
    render_menu(ctx)
    flush_feedback(ctx)

    while True:
        try:
            raw = input(make_prompt(ctx))
        except (EOFError, KeyboardInterrupt):
            print()  # newline on ^D/^C
            _clear_target_on_exit("quit")
            break

        try:
            if ctx.get("mode") == "class_select":
                handle_input(raw, ctx)
            else:
                token, _, arg = raw.strip().partition(" ")
                dispatch.call(token, arg)
        except SystemExit:
            _clear_target_on_exit("quit")
            break

        if ctx.get("render_next"):
            render_frame(ctx)
            ctx["render_next"] = False
        else:
            flush_feedback(ctx)

    _clear_target_on_exit("quit")
