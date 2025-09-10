from __future__ import annotations

from mutants.app.context import render_frame


def look_cmd(_arg: str, ctx) -> None:
    render_frame(ctx)
