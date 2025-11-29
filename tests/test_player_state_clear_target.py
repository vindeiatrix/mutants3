import sys
from typing import Any, Dict

sys.path.append("src")

from mutants.services import player_state as pstate


class DummyMonsters:
    def __init__(self, records: list[Dict[str, Any]]):
        self._records = records
        self.marked = False
        self.saved = False

    def list_all(self):
        return list(self._records)

    def get(self, monster_id: str):
        for record in self._records:
            ident = record.get("id") or record.get("instance_id")
            if ident == monster_id:
                return record
        return None

    def mark_dirty(self):
        self.marked = True

    def save(self):
        self.saved = True


def _install_state(monkeypatch, state: Dict[str, Any], monsters: DummyMonsters):
    monkeypatch.setattr(pstate, "load_state", lambda: state)
    monkeypatch.setattr(pstate, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pstate.monsters_state, "load_state", lambda: monsters)


def test_clear_target_drops_monster_aggro_for_active_player(monkeypatch):
    state: Dict[str, Any] = {
        "active": {"id": "player-1", "class": "Wizard"},
        "active_id": "player-1",
        "players": [{"id": "player-1", "class": "Wizard"}],
    }
    monster = {"id": "m1", "target_player_id": "player-1"}
    monsters = DummyMonsters([monster])

    _install_state(monkeypatch, state, monsters)

    pstate.clear_target()

    assert monster.get("target_player_id") is None
    assert monsters.marked is True
    assert monsters.saved is True


def test_clear_target_handles_player_id_in_roster(monkeypatch):
    state: Dict[str, Any] = {"players": [{"id": "player-roster", "class": "Wizard"}]}
    monster = {"id": "m2", "target_player_id": "player-roster"}
    monsters = DummyMonsters([monster])

    _install_state(monkeypatch, state, monsters)

    pstate.clear_target()

    assert monster.get("target_player_id") is None
    assert monsters.saved is True
