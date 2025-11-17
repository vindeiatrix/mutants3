import json
import sys
from pathlib import Path

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mutants import state as state_mod
from mutants.constants import CLASS_ORDER
from mutants.players import startup as player_startup
from mutants.services import player_state
from mutants.services import player_reset


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
    assert len(players) == len(CLASS_ORDER)
    thief_entry = next(entry for entry in players if entry["class"] == "Thief")
    assert thief_entry["pos"] == [2000, 0, 0]
    assert thief_entry.get("inventory", []) == []
    assert state["ions_by_class"]["Thief"] == 0


def test_load_state_rewrites_with_clean_players(state_root):
    player_path = state_root / "playerlivestate.json"
    payload = {
        "players": [
            {
                "id": "player_thief",
                "class": "Thief",
                "pos": [2024, 2, 4],
                "inventory": ["amulet"],
                "stats": {"str": 99},
            }
        ],
        "active_id": "unknown",
        "ions_by_class": {},
        "active": {"junk": True},
    }
    _write_state(player_path, payload)

    state = player_state.load_state()

    assert state.get("active_id") == "player_thief"

    with player_path.open("r", encoding="utf-8") as handle:
        written = json.load(handle)

    assert "active" not in written
    cleaned_player = written["players"][0]
    assert cleaned_player.get("id") == "player_thief"
    assert cleaned_player.get("class") == "Thief"
    assert "stats" not in cleaned_player


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
    players = {entry["class"]: entry for entry in written["players"]}
    assert players["Thief"]["pos"] == [2020, 0, 0]
    assert written["ions_by_class"]["Thief"] == 777
    assert set(written["ions_by_class"].keys()) == set(CLASS_ORDER)


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


def test_ensure_class_profiles_rebuilds_missing_classes():
    state = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "ions": 111},
            {"id": "player_thief_2", "class": "Thief", "pos": [2001, 1, 1], "ions": 222},
            {"id": "player_wizard", "class": "Wizard", "pos": [2010, 2, 3], "ions": 333},
        ],
        "active_id": "player_thief_2",
        "ions_by_class": {},
    }

    normalized = player_state.ensure_class_profiles(state)

    players = normalized["players"]
    assert [entry["class"] for entry in players] == CLASS_ORDER
    assert len({entry["id"] for entry in players}) == len(CLASS_ORDER)

    thief_entry = next(entry for entry in players if entry["class"] == "Thief")
    assert thief_entry["id"] == "player_thief_2"

    mage_entry = next(entry for entry in players if entry["class"] == "Mage")
    assert mage_entry["class"] == "Mage"
    assert mage_entry["id"]
    assert normalized["ions_by_class"]["Mage"] == mage_entry["ions"]

    assert normalized["active_id"] == thief_entry["id"]


def test_bury_by_index_preserves_class_roster(state_root, monkeypatch):
    player_path = state_root / "playerlivestate.json"
    payload = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "ions": 123},
            {"id": "player_thief_dup", "class": "Thief", "pos": [2002, 1, 1], "ions": 456},
            {"id": "player_priest", "class": "Priest", "pos": [2000, 0, 0], "ions": 789},
            {"id": "player_wizard", "class": "Wizard", "pos": [2000, 0, 0], "ions": 555},
            {"id": "player_warrior", "class": "Warrior", "pos": [2000, 0, 0], "ions": 444},
        ],
        "active_id": "player_thief_dup",
        "ions_by_class": {},
    }
    _write_state(player_path, payload)
    monkeypatch.setattr(player_reset, "_purge_player_items", lambda player_id: 0)

    updated = player_reset.bury_by_index(0)

    assert [entry["class"] for entry in updated["players"]] == CLASS_ORDER

    with player_path.open("r", encoding="utf-8") as handle:
        saved = json.load(handle)

    assert [entry["class"] for entry in saved["players"]] == CLASS_ORDER
