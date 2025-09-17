from __future__ import annotations
from typing import Any
from mutants.services import player_active as act

def party_list(ctx: dict[str, Any]) -> None:
    state = act.load_state()
    aid = state.get("active_id")
    lines = []
    for i, p in enumerate(state.get("players", []), start=1):
        marker = "★" if p.get("id") == aid else " "
        lines.append(f"{marker} {i}. {p.get('name')} [{p.get('class')}]  id={p.get('id')}")
    ctx["feedback_bus"].push("SYSTEM/INFO", "\n".join(lines) if lines else "No players found.")

def register(dispatch, ctx) -> None:
    dispatch.register("party", lambda arg: party_list(ctx))
