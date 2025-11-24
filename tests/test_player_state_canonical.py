import json
import logging
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


def test_load_state_repairs_manual_edits(state_root, caplog):
    player_path = state_root / "playerlivestate.json"
    payload = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "ions": 111},
            {"id": "player_spy", "class": "Spy", "pos": [2001, 1, 1], "ions": 222},
        ],
        "active_id": "player_spy",
        "ions_by_class": {"Thief": 111, "Spy": 222},
    }
    _write_state(player_path, payload)

    with caplog.at_level(logging.INFO):
        repaired = player_state.load_state()

    roster_classes = [entry.get("class") for entry in repaired["players"]]
    assert roster_classes == list(player_state.CANONICAL_CLASSES)
    assert set(repaired["ions_by_class"].keys()) == set(player_state.CANONICAL_CLASSES)
    assert any("canonical classes" in message for message in caplog.messages)


def test_set_active_player_switches_inventory_bags():
    state = {
        "players": [
            {
                "id": "player_thief",
                "class": "Thief",
                "pos": [2000, 0, 0],
                "inventory": ["thief-dagger"],
            },
            {
                "id": "player_mage",
                "class": "Mage",
                "pos": [2000, 0, 0],
                "inventory": ["mage-orb"],
            },
        ],
        "active_id": "player_thief",
        "bags": {"thief": ["thief-dagger"], "mage": ["mage-orb"]},
        "inventory": ["thief-dagger", "stale-item"],
    }

    player_state.set_active_player(state, "player_thief")
    assert state["inventory"] == ["thief-dagger"]

    state["inventory"] = ["cross-contamination"]
    player_state.set_active_player(state, "player_mage")

    assert state["inventory"] == ["mage-orb"]
    assert state["players"][1]["inventory"] == ["mage-orb"]
    assert "cross-contamination" not in state["inventory"]


def test_normalize_player_live_state_strips_snapshot_and_resolves_active(caplog):
    payload = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0]},
            {"id": "player_mage", "class": "Mage", "pos": [2001, 1, 1]},
        ],
        "active_id": "invalid-id",
        "active": {"id": "stale", "class": "Warrior", "pos": [2050, 5, 5]},
    }

    with caplog.at_level(logging.WARNING):
        normalized_first = player_state.normalize_player_live_state(payload)
        normalized_second = player_state.normalize_player_live_state(payload)

    assert "active" not in normalized_first
    assert normalized_first["active_id"] == "player_thief"
    assert normalized_second["active_id"] == "player_thief"
    assert len([msg for msg in caplog.messages if "forbidden 'active'" in msg]) == 1


def test_ensure_class_profiles_fills_missing_and_prunes_unknown_ions():
    state = {
        "players": [
            {"id": "player_thief", "class": "Thief", "pos": [2000, 0, 0], "ions": 111},
            {"id": "player_spelunker", "class": "Spelunker", "pos": [2005, 5, 5], "ions": 999},
        ],
        "active_id": "player_thief",
        "ions_by_class": {"Thief": 111, "Spelunker": 999, "Mage": 555},
    }

    normalized = player_state.ensure_class_profiles(state)

    classes = [entry["class"] for entry in normalized["players"]]
    assert classes == CLASS_ORDER
    assert set(normalized["ions_by_class"].keys()) == set(CLASS_ORDER)
    assert "Spelunker" not in normalized["ions_by_class"]

    priest_entry = next(entry for entry in normalized["players"] if entry["class"] == "Priest")
    assert priest_entry["id"].startswith("player_priest")


def test_sanitize_player_entry_coerces_defaults():
    used_ids: set[str] = set()
    entry = {"id": None, "class": "Thief", "pos": "bad", "inventory": "bag"}

    sanitized = player_state._sanitize_player_entry(entry, "Thief", used_ids, None)

    assert sanitized["pos"] == [2000, 0, 0]
    assert sanitized["inventory"] == []
    assert sanitized["ions"] == player_startup.START_IONS["fresh"]
    assert sanitized["Ions"] == player_startup.START_IONS["fresh"]


def test_sanitize_player_entry_allocates_unique_ids():
    used_ids: set[str] = set()

    first = player_state._sanitize_player_entry({"id": "player_thief"}, "Thief", used_ids, None)
    second = player_state._sanitize_player_entry({"id": "player_thief"}, "Thief", used_ids, None)
    third = player_state._sanitize_player_entry({"id": ""}, "Thief", used_ids, None)

    assert first["id"] == "player_thief"
    assert second["id"] == "player_thief_2"
    assert third["id"] == "player_thief_3"


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


@pytest.mark.parametrize("active_class", CLASS_ORDER)
def test_canonical_state_roundtrip_with_all_classes(state_root, active_class):
    player_path = state_root / "playerlivestate.json"
    coords_by_class = {
        cls: (2000 + idx, idx * 10, idx * 10 + 1) for idx, cls in enumerate(CLASS_ORDER, start=1)
    }
    ions_by_class = {cls: idx * 100 for idx, cls in enumerate(CLASS_ORDER, start=1)}
    players = [
        {
            "id": f"player_{cls.lower()}",
            "class": cls,
            "pos": [str(pos[0]), pos[1], pos[2]],
            "inventory": [f"{cls.lower()}-loot"],
        }
        for cls, pos in coords_by_class.items()
    ]

    payload = {
        "players": players,
        "active_id": f"player_{active_class.lower()}",
        "ions_by_class": ions_by_class,
        "active": {
            "id": f"player_{active_class.lower()}",
            "class": active_class,
            "pos": [9999, 9, 9],
            "inventory": ["transient-item"],
        },
    }

    player_state.save_state(payload)

    with player_path.open("r", encoding="utf-8") as handle:
        saved = json.load(handle)

    assert "active" not in saved
    roster = {entry["class"]: entry for entry in saved["players"]}
    assert list(roster.keys()) == CLASS_ORDER
    for cls, pos in coords_by_class.items():
        assert roster[cls]["pos"] == [int(pos[0]), int(pos[1]), int(pos[2])]
        assert roster[cls].get("inventory") == [f"{cls.lower()}-loot"]
        assert saved["ions_by_class"][cls] == ions_by_class[cls]

    missing_class = next(cls for cls in CLASS_ORDER if cls != active_class)
    mutated_roster = [entry for entry in saved["players"] if entry.get("class") != missing_class]
    mutated = dict(saved, players=mutated_roster)
    mutated["ions_by_class"].pop(missing_class, None)
    _write_state(player_path, mutated)

    loaded = player_state.load_state()

    rebuilt_roster = {entry["class"]: entry for entry in loaded["players"]}
    assert list(rebuilt_roster.keys()) == CLASS_ORDER
    assert loaded["active_id"] == roster[active_class]["id"]
    assert player_state.canonical_player_pos(loaded) == tuple(int(value) for value in coords_by_class[active_class])

    top_level_state = {
        "players": [{"id": "player_top", "class": active_class, "pos": []}],
        "active_id": "player_top",
        "position": [
            str(coords_by_class[active_class][0] + 50),
            coords_by_class[active_class][1] + 50,
            coords_by_class[active_class][2] + 50,
        ],
    }
    assert player_state.canonical_player_pos(top_level_state) == (
        coords_by_class[active_class][0] + 50,
        coords_by_class[active_class][1] + 50,
        coords_by_class[active_class][2] + 50,
    )

    default_state = {
        "players": [{"id": "player_default", "class": active_class, "pos": []}],
        "active_id": "player_default",
    }
    assert player_state.canonical_player_pos(default_state) == (2000, 0, 0)
