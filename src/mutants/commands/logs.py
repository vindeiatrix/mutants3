from __future__ import annotations

from typing import List

from mutants.app import trace as traceflags


def log_cmd(arg: str, ctx) -> None:
    parts = arg.split()
    sink = ctx["logsink"]
    if len(parts) >= 3 and parts[0] == "trace":
        if parts[1] not in ("move", "ui") or parts[2] not in ("on", "off"):
            ctx["feedback_bus"].push("SYSTEM/OK", "Usage: logs trace <move|ui> <on|off>")
            return
        name = parts[1]
        on = parts[2] == "on"
        traceflags.set_flag(name, on)
        state = "enabled" if on else "disabled"
        ctx["feedback_bus"].push("SYSTEM/OK", f"Trace {name} {state}.")
        return
    if not parts or parts[0] == "tail":
        n = int(parts[1]) if len(parts) > 1 else 50
        for line in sink.tail(n):
            print(line)
        return
    if parts[0] == "clear":
        sink.clear()
        ctx["feedback_bus"].push("SYSTEM/OK", "Logs cleared.")
        return
    # unknown subcommand -> show tail
    for line in sink.tail(50):
        print(line)


def register(dispatch, ctx) -> None:
    dispatch.register("logs", lambda arg: log_cmd(arg, ctx))
    dispatch.alias("log", "logs")
