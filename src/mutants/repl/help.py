from __future__ import annotations
from typing import Iterable


def startup_banner(ctx) -> str:
    return (
        "Mutants — classic BBS vibes.  Type 'help' for commands; 'theme mono' for no color.\n"
    )


def _as_names(maybe_names) -> Iterable[str]:
    """
    Accept either a dict-like (with .keys()) or a list/iterable of names.
    Returns an iterable of lower-cased command names.
    """
    if hasattr(maybe_names, "keys"):
        names = maybe_names.keys()  # dict-like
    else:
        names = maybe_names  # already a list/iterable
    return (str(n).lower() for n in names)


def render_help(dispatch) -> str:
    # Dispatch.list_commands() may return a dict-like or a list of names depending on router version.
    names = _as_names(dispatch.list_commands())
    cmds = sorted(names)
    lines = []
    lines.append("Available commands:")
    for c in cmds:
        lines.append(f" - {c}")
    return "\n".join(lines)
