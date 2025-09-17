from __future__ import annotations


def make_prompt(ctx) -> str:
    # Simple for now; later you can colorize based on theme palette
    if ctx.get("mode") == "class_select":
        return "Select (Bury, 1–5, ?) "
    return "> "
