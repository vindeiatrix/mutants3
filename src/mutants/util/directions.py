CANONICAL_DIRS = ("north", "south", "east", "west")

def resolve_dir(token: str) -> str | None:
    """Resolve a direction *token* to its canonical full word.

    The match is case-insensitive and accepts any unique prefix of the
    canonical directions.
    Returns the full canonical direction on a unique match or ``None`` if the
    token is empty, ambiguous or invalid.
    """
    t = (token or "").strip().lower()
    if not t:
        return None
    matches = [d for d in CANONICAL_DIRS if d.startswith(t)]
    return matches[0] if len(matches) == 1 else None
