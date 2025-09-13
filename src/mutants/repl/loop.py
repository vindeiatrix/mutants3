from __future__ import annotations
from mutants.app.context import build_context, render_frame, flush_feedback
from mutants.repl.dispatch import Dispatch
from mutants.commands.register_all import register_all
from mutants.repl.prompt import make_prompt
from mutants.repl.help import startup_banner


def main() -> None:
    ctx = build_context()
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])

    # Auto-register all commands in mutants.commands
    register_all(dispatch, ctx)

    # Optional: print a small banner or first-help hint once
    print(startup_banner(ctx))

    # Initial paint
    render_frame(ctx)

    while True:
        try:
            raw = input(make_prompt(ctx))
        except (EOFError, KeyboardInterrupt):
            print()  # newline on ^D/^C
            break

        token, _, arg = raw.strip().partition(" ")
        handled = dispatch.call(token, arg)

        if handled in {"north", "south", "east", "west", "look"}:
            render_frame(ctx)
        else:
            flush_feedback(ctx)
