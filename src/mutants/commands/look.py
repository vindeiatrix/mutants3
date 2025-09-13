from __future__ import annotations

from mutants.app.render_policy import RenderPolicy


def look_cmd(_arg: str, ctx) -> RenderPolicy:
    # Request a render; argument (optional direction) is currently ignored.
    return RenderPolicy.ROOM


def register(dispatch, ctx) -> None:
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
