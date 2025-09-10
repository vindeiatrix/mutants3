# src/mutants/main.py
# Minimal CLI that ensures player state exists (lazy init) and lets you inspect/switch the active class.

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Any, List

from mutants.bootstrap.lazyinit import ensure_player_state

STATE_DIR = "state"
PLAYER_STATE_FILE = "playerlivestate.json"


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_player_state() -> Dict[str, Any]:
    """Ensure player state exists; then load and return it."""
    state = ensure_player_state(state_dir=STATE_DIR)
    return state


def save_player_state(state: Dict[str, Any]) -> None:
    out_path = Path(STATE_DIR) / PLAYER_STATE_FILE
    atomic_write_json(out_path, state)


def list_players(state: Dict[str, Any]) -> str:
    lines = []
    active_id = state.get("active_id")
    for p in state.get("players", []):
        star = "*" if p["id"] == active_id else " "
        lines.append(
            f"{star} {p['id']}  ({p['class']})  pos={tuple(p['pos'])}  hp={p['hp']['current']}/{p['hp']['max']}  ions={p['ions']}"
        )
    return "\n".join(lines)


def get_active_player(state: Dict[str, Any]) -> Dict[str, Any]:
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p["id"] == aid:
            return p
    # Fallback: first player
    return state["players"][0]


def show_active_details(state: Dict[str, Any]) -> str:
    p = get_active_player(state)
    stats = p["stats"]
    ac = p["armour"]["armour_class"] if p.get("armour") else 0
    return (
        f"Active: {p['name']} ({p['class']})\n"
        f" pos={tuple(p['pos'])}\n"
        f" hp={p['hp']['current']}/{p['hp']['max']}  ions={p['ions']}  riblets={p['riblets']}\n"
        f" AC={ac}  exhaustion={p['exhaustion']}\n"
        f" STR={stats['str']} INT={stats['int']} WIS={stats['wis']} "
        f"DEX={stats['dex']} CON={stats['con']} CHA={stats['cha']}\n"
        f" inventory={p.get('inventory', [])}"
    )


def switch_active(state: Dict[str, Any], class_or_id: str) -> str:
    want = class_or_id.strip().lower()
    chosen_id = None
    # Try by id first, then by class name
    for p in state.get("players", []):
        if p["id"].lower() == want or p["class"].lower() == want:
            chosen_id = p["id"]
            break
    if not chosen_id:
        return "No matching class/id. Try: thief, priest, wizard, warrior, mage (or player_thief, etc.)."

    # Flip flags
    for p in state["players"]:
        p["is_active"] = (p["id"] == chosen_id)
    state["active_id"] = chosen_id
    save_player_state(state)
    return f"Active class set to {chosen_id}."


def rename_active(state: Dict[str, Any], new_name: str) -> str:
    p = get_active_player(state)
    p["name"] = new_name
    save_player_state(state)
    return f"Renamed active character to '{new_name}'."


def main() -> None:
    state = load_player_state()

    print("Mutants — dev shell")
    print("Type 'help' for commands. Type 'exit' to quit.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()
        arg = " ".join(parts[1:]) if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            print("Goodbye.")
            break

        elif cmd in ("help", "?"):
            print(
                "Commands:\n"
                "  list                 - list all classes and show which is active\n"
                "  whoami               - details for the active class\n"
                "  switch <class|id>    - set the active class (e.g., switch warrior)\n"
                "  where                - print active position [year, x, y]\n"
                "  rename <name>        - rename the active class\n"
                "  save                 - write player state to disk\n"
                "  help                 - this help\n"
                "  exit                 - quit"
            )

        elif cmd == "list":
            print(list_players(state))

        elif cmd == "whoami":
            print(show_active_details(state))

        elif cmd == "switch":
            if not arg:
                print("Usage: switch <class|id>")
            else:
                print(switch_active(state, arg))

        elif cmd == "where":
            p = get_active_player(state)
            print(tuple(p["pos"]))

        elif cmd == "rename":
            if not arg:
                print("Usage: rename <new name>")
            else:
                print(rename_active(state, arg))

        elif cmd == "save":
            save_player_state(state)
            print("Player state saved.")

        else:
            print("Unknown command. Type 'help'.")

if __name__ == "__main__":
    main()
