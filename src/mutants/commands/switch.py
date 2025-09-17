from __future__ import annotations
from typing import Any
from mutants.services import player_active as act

def do_switch(arg: str, ctx: dict[str, Any]) -> None:
    q = (arg or "").strip()
    state = act.load_state()
    target = act.resolve_candidate(state, q)
    if not target:
        ctx["feedback_bus"].push("SYSTEM/ERROR", "Switch whom? Try: switch <id|name|class|index> or run `party`.")
        return
    try:
        new_state = act.set_active(target)
    except ValueError as e:
        ctx["feedback_bus"].push("SYSTEM/ERROR", str(e))
        return
    # Keep runtime context coherent so VM/UI update immediately.
    ctx["player_state"] = new_state
    ctx["render_next"] = True
    # Optional: nudge the renderer to show the new room without extra text noise.
    ctx["feedback_bus"].push("SYSTEM/OK", f"Now controlling {target}.")

def register(dispatch, ctx) -> None:
    dispatch.register("switch", lambda arg: do_switch(arg, ctx))
