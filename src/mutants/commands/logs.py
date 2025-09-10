from __future__ import annotations

from typing import List


def log_cmd(arg: str, ctx) -> None:
    parts = arg.split()
    sink = ctx["logsink"]
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
    dispatch.register("log", lambda arg: log_cmd(arg, ctx))
