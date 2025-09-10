# Minimal REPL to exercise player state (list/whoami/switch/where/rename/save/exit).

from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Dict

from mutants.bootstrap.lazyinit import ensure_player_state

STATE_DIR = "state"
PLAYER_STATE_FILE = "playerlivestate.json"

def atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
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
    y, x = p.get("pos", [2000,0,0])[1:3]
    print(f"Year {p.get('pos',[2000,0,0])[0]} at ({x},{y})")

def help_text() -> None:
    print("Commands: list, whoami, switch <class|id>, where, rename <name>, save, help, exit")

def main() -> None:
    state = ensure_player_state()
    help_text()
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye"); break
        if not raw: 
            continue
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("exit", "quit"): break
        elif cmd == "help": help_text()
        elif cmd == "list": cmd_list(state)
        elif cmd == "whoami": cmd_whoami(state)
        elif cmd == "where": cmd_where(state)
        elif cmd == "switch": print(set_active(state, arg) if arg else "Usage: switch <class|id>")
        elif cmd == "rename": print(rename_active(state, arg) if arg else "Usage: rename <name>")
        elif cmd == "save": save_player_state(state); print("Player state saved.")
        else: print("Unknown command. Type 'help'.")

if __name__ == "__main__":
    main()
