import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import monster_actions
from mutants.services.monster_spawner import MonsterSpawnerController


class DummyInstances:
    def __init__(self, records: Iterable[Mapping[str, Any]] | None = None) -> None:
        self._records = [dict(record) for record in records or []]
        self.spawned: list[Dict[str, Any]] = []
        self.saved = False

    def list_all(self) -> list[Mapping[str, Any]]:
        return list(self._records)

    def _add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.spawned.append(dict(payload))
        return payload

    def save(self) -> None:
        self.saved = True


class DummyWorld:
    def __init__(self, tiles: Iterable[Mapping[str, Any]]) -> None:
        self._tiles = list(tiles)

    def iter_tiles(self) -> Iterable[Mapping[str, Any]]:
        return list(self._tiles)


def _template() -> dict[str, Any]:
    return {
        "id": "goblin",
        "monster_id": "goblin",
        "name": "Goblin",
        "pinned_years": [2000],
        "hp": {"current": 4, "max": 4},
        "armour_class": 1,
        "level": 1,
        "ions": 0,
        "riblets": 0,
        "bag": [],
        "armour_slot": None,
        "spells": [],
    }


def _controller(time_value: float = 100.0) -> MonsterSpawnerController:
    instances = DummyInstances([])

    def _world_loader(year: int) -> DummyWorld:
        if year == 2000:
            return DummyWorld([{"pos": [2000, 0, 0]}])
        return DummyWorld([])

    return MonsterSpawnerController(
        templates=[_template()],
        instances=instances,
        world_loader=_world_loader,
        rng=random.Random(0),
        time_func=lambda: time_value,
        floor_per_year=1,
        spawn_interval=60.0,
        spawn_jitter=0.0,
    )


def test_notify_monster_death_marks_year_dirty_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    controller = _controller()
    year_state = controller._years[2000]
    year_state.next_spawn_at = 999.0

    caplog.set_level(logging.INFO, "mutants.services.monster_spawner")

    controller.notify_monster_death({"pos": [2000, 5, 5]})

    assert controller.pending_respawn_years() == frozenset({2000})
    assert year_state.next_spawn_at == pytest.approx(100.0)
    assert "respawn stub" in caplog.text


def test_monster_actions_forwards_to_spawner() -> None:
    calls: list[Mapping[str, Any] | None] = []

    class Recorder:
        def notify_monster_death(self, payload: Mapping[str, Any] | None) -> None:
            calls.append(payload)

    ctx = {"monster_spawner": Recorder()}
    payload = {"pos": [2000, 1, 2]}

    monster_actions.notify_monster_death(payload, ctx=ctx)

    assert calls == [payload]

