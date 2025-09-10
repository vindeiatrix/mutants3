from __future__ import annotations
from mutants.repl.help import render_help


def register(dispatch, ctx):
    bus = ctx["feedback_bus"]

    def _help(arg: str = ""):
        text = render_help(dispatch)
        # For long help, you might want to print directly; for now use feedback:
        bus.push("SYSTEM/OK", text)

    dispatch.register("help", _help)
    dispatch.alias("h", "help")
