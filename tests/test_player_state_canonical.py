import json
from pathlib import Path

import pytest

from mutants import state as state_mod
from mutants.services import player_state


@pytest.fixture(autouse=True)
def _reset_player_state_globals(monkeypatch):
    monkeypatch.setattr(player_state, "_ACTIVE_SNAPSHOT_WARNING_EMITTED", False)


@pytest.fixture
def state_root(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)
    return tmp_path


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_load_state_strips_persisted_active(state_root):
    player_path = state_root / "playerlivestate.json"
    payload = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "inventory": []}
        ],
        "active_id": "player_thief",
        "ions_by_class": {},
        "active": {
            "id": "player_thief",
            "class": "Thief",
            "pos": [2022, 1, 2],
            "inventory": ["mysterious-orb"],
            "ions": 123,
        },
    }
    _write_state(player_path, payload)

    state = player_state.load_state()

    assert "active" not in state
    players = state["players"]
    assert len(players) == 1
    entry = players[0]
    assert entry["pos"] == [2022, 1, 2]
    assert entry["inventory"] == ["mysterious-orb"]
    assert state["ions_by_class"]["Thief"] == 123


def test_save_state_strips_active_snapshot(state_root):
    player_path = state_root / "playerlivestate.json"
    payload = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2020, 0, 0], "inventory": []}
        ],
        "active_id": "player_thief",
        "ions_by_class": {"Thief": 777},
        "active": {"id": "player_thief", "class": "Thief", "pos": [2025, 3, 4]},
    }

    player_state.save_state(payload)

    with player_path.open("r", encoding="utf-8") as handle:
        written = json.load(handle)

    assert "active" not in written
    assert written["players"][0]["pos"] == [2020, 0, 0]
    assert written["ions_by_class"] == {"Thief": 777}


def test_update_player_pos_preserves_unique_entries():
    state = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0]},
            {"id": "player_priest", "class": "Priest", "pos": [2000, 0, 0]},
        ],
        "active_id": "player_thief",
    }

    updated = player_state.update_player_pos(state, "Thief", (2100, 5, 6))

    assert updated == [2100, 5, 6]
    players = state["players"]
    assert len(players) == 2
    thief_entry = next(entry for entry in players if entry["id"] == "player_thief")
    assert thief_entry["pos"] == [2100, 5, 6]
    assert state["pos"] == [2100, 5, 6]
