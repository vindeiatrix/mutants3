import logging
import random
from pathlib import Path

import pytest

from mutants.registries import monsters_instances
from mutants.services import monster_spawner, monsters_state


@pytest.fixture(autouse=True)
def _reset_monster_cache():
    monsters_state.invalidate_cache()
    yield
    monsters_state.invalidate_cache()


def _build_state(tmp_path: Path):
    raw = [
        {
            "id": "ogre#1",
            "name": "Ogre",
            "level": 1,
            "stats": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "hp": {"current": 5, "max": 5},
            "bag": [{"item_id": "club", "iid": "ogre#club"}],
            "armour_slot": {"item_id": "leather", "iid": "ogre#leather"},
        }
    ]
    normalized = monsters_state.normalize_records(raw, catalog={})
    return monsters_state.MonstersState(tmp_path / "instances.json", normalized)


def test_level_up_logs_playersdbg(monkeypatch, tmp_path, caplog):
    state = _build_state(tmp_path)
    monkeypatch.setattr(monsters_state.pstate, "_pdbg_enabled", lambda: True)
    monkeypatch.setattr(monsters_state.pstate, "_pdbg_setup_file_logging", lambda: None)

    with caplog.at_level(logging.INFO, logger="mutants.playersdbg"):
        assert state.level_up_monster("ogre#1")

    messages = [record.message for record in caplog.records if "MON-LVL" in record.message]
    assert messages, "expected MON-LVL log record"
    message = messages[-1]
    assert "id=ogre#1" in message
    assert "lvl=2" in message
    assert "Δlvl=+1" in message
    assert "stats=str:+10" in message
    assert "hp=+10" in message


def test_kill_logs_playersdbg(monkeypatch, tmp_path, caplog):
    state = _build_state(tmp_path)
    monkeypatch.setattr(monsters_state.pstate, "_pdbg_enabled", lambda: True)
    monkeypatch.setattr(monsters_state.pstate, "_pdbg_setup_file_logging", lambda: None)

    with caplog.at_level(logging.INFO, logger="mutants.playersdbg"):
        summary = state.kill_monster("ogre#1")

    assert summary["monster"]["hp"]["current"] == 0
    messages = [record.message for record in caplog.records if "MON-KILL" in record.message]
    assert messages, "expected MON-KILL log record"
    message = messages[-1]
    assert "id=ogre#1" in message
    assert "drops=2" in message
    assert "bag=1" in message
    assert "armour=yes" in message


class _DummyWorld:
    def __init__(self, year: int):
        self._year = year

    def iter_tiles(self):
        yield {"pos": [self._year, 1, 2]}


def test_spawn_logs_playersdbg(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(monster_spawner.pstate, "_pdbg_enabled", lambda: True)
    monkeypatch.setattr(monster_spawner.pstate, "_pdbg_setup_file_logging", lambda: None)

    template = {
        "id": "ogre",
        "name": "Ogre",
        "pinned_years": [2000],
        "hp": {"max": 5},
        "armour_class": 3,
        "level": 2,
        "bag": [{"item_id": "club"}],
        "innate_attack": {"name": "Smash", "power_base": 1, "power_per_level": 1},
    }
    instances = monsters_instances.MonstersInstances(str(tmp_path / "instances.json"), [])

    controller = monster_spawner.MonsterSpawnerController(
        templates=[template],
        instances=instances,
        world_loader=lambda year: _DummyWorld(year),
        rng=random.Random(0),
        time_func=lambda: 10.0,
        floor_per_year=1,
        spawn_interval=1.0,
        spawn_jitter=0.0,
    )

    with caplog.at_level(logging.INFO, logger="mutants.playersdbg"):
        controller.tick()

    messages = [record.message for record in caplog.records if "MON-SPAWN" in record.message]
    assert messages, "expected MON-SPAWN log record"
    message = messages[-1]
    assert "kind=ogre" in message
    assert "pos=[2000, 1, 2]" in message
    assert "lvl=2" in message
    assert "hp=" in message
