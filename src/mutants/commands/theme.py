from __future__ import annotations

from pathlib import Path

from mutants.ui.themes import load_theme


def theme_cmd(arg: str, ctx) -> None:
    name = arg.strip()
    if not name:
        ctx["feedback_bus"].push("SYSTEM/ERR", "Usage: theme <name>")
        return
    path = Path("state/ui/themes") / f"{name}.json"
    try:
        theme = load_theme(str(path))
    except Exception:
        ctx["feedback_bus"].push("SYSTEM/ERR", f"Theme not found: {name}")
        return
    ctx["theme"] = theme
    ctx["feedback_bus"].push("SYSTEM/OK", f"Theme switched to {name}.")


def register(dispatch, ctx) -> None:
    dispatch.register("theme", lambda arg: theme_cmd(arg, ctx))
