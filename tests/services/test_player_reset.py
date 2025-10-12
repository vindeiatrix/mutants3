from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from mutants import env, state
from mutants.bootstrap import lazyinit
from mutants.players import startup as player_startup
from mutants.services import player_reset, player_state


@pytest.fixture
def configure_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    env._CONFIG_LOGGED = False  # reset cached log state between tests
    return tmp_path


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bury_purges_owned_items_and_resets_inventory(
    configure_state_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_path = env.get_state_database_path()
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS items_instances (
                iid TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                owner TEXT,
                enchant INT,
                condition INT,
                charges INTEGER DEFAULT 0,
                origin TEXT,
                drop_source TEXT,
                created_at INTEGER NOT NULL CHECK(created_at >= 0)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                wield_item_id TEXT,
                armour_item_id TEXT
            )
            """
        )
        con.execute(
            "INSERT OR REPLACE INTO players(player_id, wield_item_id, armour_item_id) VALUES (?, ?, ?)",
            ("player_thief", "iid-weapon", "iid-armour"),
        )
        items = (
            ("iid-weapon", "short-sword", "player_thief"),
            ("iid-armour", "leather-armour", "player_thief"),
            ("iid-pack", "backpack", "player_thief"),
            ("iid-other", "coin", "player_priest"),
        )
        for iid, item_id, owner in items:
            con.execute(
                """
                INSERT OR REPLACE INTO items_instances (
                    iid, item_id, year, x, y, owner, enchant, condition, charges, origin, drop_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, item_id, 2000, 0, 0, owner, 0, 100, 0, "test", None, 0),
            )

    player_entry = {
        "id": "player_thief",
        "class": "Thief",
        "pos": [2000, 0, 0],
        "stats": {"str": 10, "int": 10, "wis": 10, "dex": 10, "con": 10, "cha": 10},
        "hp": {"current": 10, "max": 10},
        "exhaustion": 0,
        "exp_points": 0,
        "level": 1,
        "riblets": 0,
        "ions": 1_200,
        "Ions": 1_200,
        "armour": {"wearing": "iid-armour", "armour_class": 1},
        "inventory": ["iid-weapon", "iid-armour", "iid-pack"],
        "wielded": "iid-weapon",
        "wielded_by_class": {"Thief": "iid-weapon"},
        "equipment_by_class": {"Thief": {"armour": "iid-armour"}},
        "ready_target_by_class": {"Thief": None},
        "bags": {"Thief": ["iid-weapon", "iid-armour", "iid-pack"]},
    }
    state_payload = {
        "players": [player_entry],
        "active_id": "player_thief",
        "ions_by_class": {"Thief": 1_200},
        "active": {
            "id": "player_thief",
            "class": "Thief",
            "pos": [2000, 0, 0],
            "inventory": ["iid-weapon", "iid-armour", "iid-pack"],
            "ions": 1_200,
            "Ions": 1_200,
        },
    }
    state_file = state.state_path("playerlivestate.json")
    _write_state(state_file, state_payload)

    caplog.set_level(logging.INFO, logger="mutants.services.player_reset")
    player_reset.bury_by_index(0)

    with sqlite3.connect(db_path) as con:
        remaining = con.execute(
            "SELECT COUNT(*) FROM items_instances WHERE owner = ?", ("player_thief",)
        ).fetchone()[0]
        assert remaining == 0
        wield_row = con.execute(
            "SELECT wield_item_id, armour_item_id FROM players WHERE player_id = ?",
            ("player_thief",),
        ).fetchone()
        assert wield_row == (None, None)

    updated = player_state.load_state()
    updated_player = updated["players"][0]
    assert updated_player["inventory"] == []
    assert updated_player["wielded"] is None
    assert updated_player["armour"]["wearing"] is None
    assert updated_player["bags"]["Thief"] == []
    assert updated_player["ions"] == 30_000
    assert updated_player["Ions"] == 30_000
    assert updated["ions_by_class"]["Thief"] == 30_000

    log_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Removed 3 item rows for player_thief during bury" in message
        for message in log_messages
    )


def test_fresh_creation_grants_uniform_starting_ions(
    configure_state_root: Path,
) -> None:
    state_data = lazyinit.ensure_player_state(
        state_dir=str(configure_state_root),
        out_name="playerlivestate.json",
    )

    ions_map = state_data.get("ions_by_class", {})
    assert ions_map
    for player in state_data["players"]:
        assert player["ions"] == 30_000
        assert player["Ions"] == 30_000
        assert ions_map.get(player["class"]) == 30_000

    loaded = player_state.load_state()
    assert loaded.get("ions_by_class")
    for amount in loaded["ions_by_class"].values():
        assert amount == 30_000


@pytest.mark.skip(reason="Resurrection flow not yet implemented")
def test_resurrection_grants_reduced_starting_ions_placeholder(
    configure_state_root: Path,
) -> None:
    player = {"class": "Thief"}
    state_payload = {"players": [player], "active_id": "player_thief"}
    player_startup.grant_starting_ions(player, "resurrected", state=state_payload)
    assert player["ions"] == player_startup.START_IONS["resurrected"]
