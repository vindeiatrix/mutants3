from __future__ import annotations


def make_prompt(ctx) -> str:
    """
    Build the REPL prompt. Class selection uses an amber prompt to match reference;
    normal gameplay uses the simple "> ".
    """

    if ctx.get("mode") == "class_select":
        return "\x1b[33mSelect (Bury, 1-5, ?)\x1b[0m "
    return "> "
