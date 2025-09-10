from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from mutants.app import context
from mutants.commands.look import look_cmd
from mutants.commands.move import move
from mutants.commands.theme import theme_cmd
from mutants.commands.logs import log_cmd
from mutants.repl.dispatch import Dispatch

STATE_DIR = "state"
PLAYER_STATE_FILE = "playerlivestate.json"


def atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_player_state(state: Dict[str, Any]) -> None:
    atomic_write_json(Path(STATE_DIR) / PLAYER_STATE_FILE, state)


def active(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def set_active(state: Dict[str, Any], player_id: str) -> str:
    for p in state.get("players", []):
        if p.get("id") == player_id or p.get("class", "").lower() == player_id.lower():
            state["active_id"] = p["id"]
            return f"Active set to {p['name']} ({p['class']})."
    return "No such player."


def rename_active(state: Dict[str, Any], new_name: str) -> str:
    p = active(state)
    p["name"] = new_name
    return f"Renamed active to {new_name}."


def cmd_list(state: Dict[str, Any]) -> None:
    aid = state.get("active_id")
    for p in state.get("players", []):
        mark = "*" if p["id"] == aid else " "
        print(f"{mark} {p['id']}: {p['name']} ({p['class']})")


def cmd_whoami(state: Dict[str, Any]) -> None:
    p = active(state)
    print(json.dumps(p, indent=2))


def cmd_where(state: Dict[str, Any]) -> None:
    p = active(state)
    y, x = p.get("pos", [2000, 0, 0])[1:3]
    print(f"Year {p.get('pos',[2000,0,0])[0]} at ({x},{y})")


def help_text() -> None:
    print(
        "Commands: north/n, south/s, east/e, west/w, look, "
        "list, whoami, switch <class|id>, where, rename <name>, save, help, exit"
    )


def main() -> None:
    ctx = context.build()
    dispatch = Dispatch(ctx["feedback_bus"])
    dispatch.register("look", lambda arg: look_cmd(arg, ctx))
    dispatch.register("north", lambda arg: move("N", ctx))
    dispatch.alias("n", "north")
    dispatch.register("south", lambda arg: move("S", ctx))
    dispatch.alias("s", "south")
    dispatch.register("east", lambda arg: move("E", ctx))
    dispatch.alias("e", "east")
    dispatch.register("west", lambda arg: move("W", ctx))
    dispatch.alias("w", "west")
    dispatch.register("theme", lambda arg: theme_cmd(arg, ctx))
    dispatch.register("log", lambda arg: log_cmd(arg, ctx))
    dispatch.register("list", lambda arg: cmd_list(ctx["player_state"]))
    dispatch.register("whoami", lambda arg: cmd_whoami(ctx["player_state"]))
    dispatch.register("where", lambda arg: cmd_where(ctx["player_state"]))
    dispatch.register(
        "switch",
        lambda arg: print(
            set_active(ctx["player_state"], arg) if arg else "Usage: switch <class|id>"
        ),
    )
    dispatch.register(
        "rename",
        lambda arg: print(
            rename_active(ctx["player_state"], arg)
            if arg
            else "Usage: rename <name>"
        ),
    )
    dispatch.register(
        "save",
        lambda arg: (save_player_state(ctx["player_state"]), print("Player state saved.")),
    )

    help_text()
    context.render_frame(ctx)
    while True:
        try:
            raw = input()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        raw = raw.strip()
        if not raw:
            context.render_frame(ctx)
            continue
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            break
        if cmd == "help":
            help_text()
        else:
            dispatch.call(cmd, arg)
        context.render_frame(ctx)
