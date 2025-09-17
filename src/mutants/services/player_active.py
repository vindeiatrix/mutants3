from __future__ import annotations
from typing import Dict, Any, Optional
from pathlib import Path
from mutants.io.atomic import atomic_write_json
import json, os

PLAYER_PATH = Path(os.getcwd()) / "state" / "playerlivestate.json"

def _path() -> Path:
    return PLAYER_PATH

def load_state() -> Dict[str, Any]:
    with _path().open("r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: Dict[str, Any]) -> None:
    atomic_write_json(_path(), state)

def set_active(active_id: str) -> Dict[str, Any]:
    """
    Switches the active player by id, writes state atomically, returns new state.
    No-op if already active.
    """
    state = load_state()
    ids = [p.get("id") for p in state.get("players", [])]
    if active_id not in ids:
        raise ValueError(f"Unknown player id: {active_id}")
    if state.get("active_id") == active_id:
        return state
    state["active_id"] = active_id
    save_state(state)
    return state

def resolve_candidate(state: Dict[str, Any], q: str) -> Optional[str]:
    """
    Accepts id | name | class | 1-based index and returns a matching player id.
    """
    qn = (q or "").strip().lower()
    if not qn:
        return None
    players = state.get("players", [])
    # 1) direct id
    for p in players:
        pid = (p.get("id") or "").lower()
        if pid == qn:
            return p.get("id")
    # 2) by name or class
    for p in players:
        if (p.get("name") or "").lower() == qn or (p.get("class") or "").lower() == qn:
            return p.get("id")
    # 3) by 1-based index
    if qn.isdigit():
        i = int(qn) - 1
        if 0 <= i < len(players):
            return players[i].get("id")
    return None
