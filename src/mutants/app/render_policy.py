from __future__ import annotations

from enum import Enum, auto


class RenderPolicy(Enum):
    """Rendering guard returned by commands.

    Only ``ROOM`` triggers a re-render of the current room. All other
    commands should return ``NEVER`` so the REPL can avoid unnecessary
    painting.
    """

    NEVER = auto()
    ROOM = auto()
