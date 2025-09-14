from __future__ import annotations

from typing import Optional

# Canonical direction vectors (right-handed grid):
# x increases to the east; y increases to the north.
DELTA = {
    "n": (0, 1),
    "s": (0, -1),
    "e": (1, 0),
    "w": (-1, 0),
    "north": (0, 1),
    "south": (0, -1),
    "east": (1, 0),
    "west": (-1, 0),
}

# Opposite direction lookup
OPP = {
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
}

CANONICAL_DIRS = ("north", "south", "east", "west")


def vec(direction: str) -> tuple[int, int]:
    """Return (dx, dy) for any short/long direction key."""
    return DELTA.get(direction.lower(), (0, 0))


def opposite(direction: str) -> str:
    """Return the opposite direction, preserving short/long form if given."""
    d = direction.lower()
    return OPP.get(d, d)


def resolve_dir(token: Optional[str]) -> Optional[str]:
    """Resolve *token* to a canonical direction or ``None``.

    Any unique prefix of the cardinal directions is accepted, case-insensitively.
    ``None`` is returned for empty, invalid, or ambiguous tokens.
    """
    if not token:
        return None
    t = token.strip().lower()
    if not t:
        return None
    matches = [d for d in CANONICAL_DIRS if d.startswith(t)]
    if len(matches) == 1:
        return matches[0]
    return None
