from __future__ import annotations

from typing import Any, Dict


def quit_cmd(arg: str, ctx: Dict[str, Any]) -> str:
    state_mgr = ctx.get("state_manager")
    if state_mgr is not None:
        state_mgr.save_on_exit()
    bus = ctx.get("feedback_bus")
    if bus is not None:
        bus.push("SYSTEM/OK", "Goodbye!")
    return "__QUIT__"


def register(dispatch, ctx) -> None:
    dispatch.register("quit", lambda arg: quit_cmd(arg, ctx))
    dispatch.alias("q", "quit")
