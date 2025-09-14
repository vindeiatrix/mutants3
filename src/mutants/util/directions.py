from typing import Optional

CANONICAL_DIRS = ("north", "south", "east", "west")


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
