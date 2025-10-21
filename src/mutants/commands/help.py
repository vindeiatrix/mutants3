from __future__ import annotations
from mutants.repl.help import render_help


def register(dispatch, ctx):
    bus = ctx["feedback_bus"]

    def _help(arg: str = ""):
        topic = (arg or "").strip().lower()
        if topic == "debug":
            from . import debug as debug_cmds

            text = debug_cmds.render_debug_help()
        else:
            text = render_help(dispatch)
        # For long help, you might want to print directly; for now use feedback:
        bus.push("SYSTEM/OK", text)

    dispatch.register("help", _help)
    dispatch.alias("h", "help")
