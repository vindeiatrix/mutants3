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
    state_mgr = ctx.get("state_manager")
    screen_mgr = ctx.get("screen_manager")

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

        stripped = raw.strip()
        if screen_mgr and screen_mgr.in_selection():
            screen_mgr.handle_selection(stripped, ctx)
            if ctx.get("render_next"):
                render_frame(ctx)
                ctx["render_next"] = False
            continue

        token, _, arg = stripped.partition(" ")
        executed = dispatch.call(token, arg)
        if state_mgr:
            state_mgr.on_command_executed(executed)

        if ctx.get("render_next"):
            render_frame(ctx)
            ctx["render_next"] = False
        else:
            flush_feedback(ctx)

    if state_mgr:
        state_mgr.save_on_exit()
