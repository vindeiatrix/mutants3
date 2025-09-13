from __future__ import annotations

def look_cmd(_arg: str, ctx) -> None:
    # REPL loop triggers rendering for look; the command itself does nothing.
    pass


def register(dispatch, ctx) -> None:
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
