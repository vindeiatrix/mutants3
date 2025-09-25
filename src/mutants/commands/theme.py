from __future__ import annotations

import json

from mutants.state import state_path
from mutants.ui.themes import load_theme
from mutants.ui import styles as st


def theme_cmd(arg: str, ctx) -> None:
    name = arg.strip()
    if not name:
        ctx["feedback_bus"].push("SYSTEM/ERR", "Usage: theme <name>")
        return
    path = state_path("ui", "themes", f"{name}.json")
    try:
        theme = load_theme(str(path))
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        ctx["feedback_bus"].push("SYSTEM/ERR", f"Theme not found: {name}")
        return
    except json.JSONDecodeError:
        ctx["feedback_bus"].push("SYSTEM/ERR", f"Theme file is invalid JSON: {name}")
        return
    ctx["theme"] = theme

    # Wire theme to palette + ANSI
    if theme.colors_path:
        st.set_colors_map_path(theme.colors_path)
    else:
        st.set_colors_map_path(None)
    st.reload_colors_map()
    st.set_ansi_enabled(theme.ansi_enabled)

    ctx["feedback_bus"].push("SYSTEM/OK", f"Theme switched to {name}.")


def register(dispatch, ctx) -> None:
    dispatch.register("theme", lambda arg: theme_cmd(arg, ctx))
