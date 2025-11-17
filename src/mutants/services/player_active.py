from __future__ import annotations

from typing import Any, Dict, Optional

from mutants.services import player_state


def load_state() -> Dict[str, Any]:
    return player_state.load_state(source="player_active.load_state")


def save_state(state: Dict[str, Any]) -> None:
    player_state.save_state(state, reason="player_active.save_state")

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
    prev_class = player_state.get_active_class(state)

    target_player: Optional[Dict[str, Any]] = None
    players = state.get("players", [])
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            if player.get("id") == active_id:
                target_player = player
                break

    def _extract_class(payload: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        candidate = payload.get("class")
        if isinstance(candidate, str) and candidate:
            return candidate
        candidate = payload.get("name")
        if isinstance(candidate, str) and candidate:
            return candidate
        return None

    next_class = _extract_class(target_player)
    if not next_class:
        next_class = prev_class

    state["active_id"] = active_id
    updated = player_state.on_class_switch(prev_class, next_class, state)
    updated["active_id"] = active_id
    # keep any in-memory active view aligned for callers using it immediately
    if isinstance(updated.get("active"), dict) and isinstance(next_class, str) and next_class:
        updated["active"]["class"] = next_class
    save_state(updated)
    return updated

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
