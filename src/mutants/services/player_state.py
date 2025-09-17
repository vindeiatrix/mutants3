from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from mutants.io.atomic import atomic_write_json

def _player_path() -> Path:
    return Path(os.getcwd()) / "state" / "playerlivestate.json"


def load_state() -> Dict[str, Any]:
    try:
        with _player_path().open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"players": [], "active_id": None}


def save_state(state: Dict[str, Any]) -> None:
    atomic_write_json(_player_path(), state)


def get_active_pair(
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a tuple of (state, active_player_dict).

    Falls back to the first player if the active_id cannot be resolved. If no
    players exist, the active portion of the tuple is an empty dict.
    """

    st = state or load_state()
    players = st.get("players")
    if isinstance(players, list) and players:
        aid = st.get("active_id")
        active: Optional[Dict[str, Any]] = None
        for player in players:
            if player.get("id") == aid:
                active = player
                break
        if active is None:
            active = players[0]
        return st, active or {}
    # Legacy single-player format: treat the root state as the active player.
    return st, st


def mutate_active(
    mutator: Callable[[Dict[str, Any], Dict[str, Any]], None]
) -> Dict[str, Any]:
    """Load state, apply ``mutator`` to the active player, and persist.

    ``mutator`` receives the full state and the active player dict. The
    updated state object is returned. If no active player is available the
    mutator is not invoked and the state is returned unchanged.
    """

    state, active = get_active_pair()
    if not active:
        return state
    mutator(state, active)
    save_state(state)
    return state
