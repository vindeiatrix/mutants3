from __future__ import annotations

def look_cmd(_arg: str, ctx) -> None:
    # The REPL loop re-renders after each command; look is a no-op.
    pass


def register(dispatch, ctx) -> None:
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
