from __future__ import annotations

from typing import Any, Dict, List, Tuple

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.debug import turnlog
from mutants.registries import items_instances as itemsreg
from mutants.services import monsters_state
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_actions import execute_random_action
from mutants.services.monster_ai.pursuit import attempt_pursuit


class FixedRNG:
    def __init__(self, value: int):
        self.value = value

    def randrange(self, upper: int) -> int:
        return int(self.value)


class DummyWorld:
    def __init__(self, tiles: Dict[Tuple[int, int], Dict[str, Any]]):
        self.tiles = tiles

    def get_tile(self, year: int, x: int, y: int) -> Dict[str, Any] | None:
        return self.tiles.get((int(x), int(y)))


def _make_tile(open_dirs: List[str]) -> Dict[str, Any]:
    edges: Dict[str, Dict[str, Any]] = {}
    for dir_code in ("N", "S", "E", "W"):
        base = 0 if dir_code in open_dirs else 2
        edges[dir_code] = {"base": base, "gate_state": 0, "key_type": None, "spell_block": 0}
    return {"edges": edges}


@pytest.fixture(autouse=True)
def _turnlog_events(monkeypatch):
    events: List[Tuple[str, Dict[str, Any]]] = []

    def _emit(ctx: Any, kind: str, **meta: Any) -> None:
        events.append((kind, meta))

    monkeypatch.setattr(turnlog, "emit", _emit)
    return events


@pytest.fixture(autouse=True)
def _disable_refresh(monkeypatch):
    monkeypatch.setattr(monsters_state, "_refresh_monster_derived", lambda monster: None)


@pytest.fixture(autouse=True)
def _empty_ground(monkeypatch):
    monkeypatch.setattr(itemsreg, "list_instances_at", lambda year, x, y: [])


def test_attempt_pursuit_moves_on_success(monkeypatch, _turnlog_events):
    tiles = {
        (0, 0): _make_tile(["E"]),
        (1, 0): _make_tile(["W"]),
    }
    world = DummyWorld(tiles)

    ctx = {"monster_ai_world_loader": lambda year: world}

    monster = {
        "id": "m1",
        "pos": [2000, 0, 0],
        "bag": [],
        "hp": {"current": 100, "max": 100},
        "ions": 50,
        "ions_max": 100,
    }

    rng = FixedRNG(5)
    result = attempt_pursuit(monster, (2000, 1, 0), rng, ctx=ctx, config=CombatConfig())
    assert result is True
    assert monster["pos"] == [2000, 1, 0]
    assert any(kind == "AI/PURSUIT" and meta["success"] for kind, meta in _turnlog_events)


def test_attempt_pursuit_penalties_block(monkeypatch, _turnlog_events):
    monkeypatch.setattr(itemsreg, "list_instances_at", lambda year, x, y: [{"item_id": "GEM"}])
    tiles = {
        (0, 0): _make_tile(["E"]),
        (1, 0): _make_tile(["W"]),
    }
    world = DummyWorld(tiles)

    ctx = {"monster_ai_world_loader": lambda year: world}
    monster = {
        "id": "m2",
        "pos": [2000, 0, 0],
        "bag": [{"iid": "w1", "item_id": itemsreg.BROKEN_WEAPON_ID, "enchant_level": 0}],
        "wielded": "w1",
        "hp": {"current": 30, "max": 100},
        "ions": 10,
        "ions_max": 100,
    }
    rng = FixedRNG(50)
    result = attempt_pursuit(monster, (2000, 1, 0), rng, ctx=ctx, config=CombatConfig())
    assert result is False
    last_kind, last_meta = _turnlog_events[-1]
    assert last_kind == "AI/PURSUIT"
    assert last_meta["success"] is False
    assert "roll=" in last_meta["reason"]


def test_execute_random_action_pursuit_consumes_turn(monkeypatch, _turnlog_events):
    tiles = {
        (0, 0): _make_tile(["E"]),
        (1, 0): _make_tile(["W"]),
    }
    world = DummyWorld(tiles)

    class Marker:
        def __init__(self) -> None:
            self.marked = False

        def mark_dirty(self) -> None:
            self.marked = True

    marker = Marker()

    def fake_process(monster, ctx, rng):
        return {}

    monkeypatch.setattr("mutants.services.monster_ai.inventory.process_pending_drops", fake_process)

    def fake_cascade(monster, ctx):
        raise AssertionError("Cascade should not run when pursuit succeeds")

    monkeypatch.setattr("mutants.services.monster_ai.cascade.evaluate_cascade", fake_cascade)

    ctx = {
        "monster_ai_world_loader": lambda year: world,
        "monsters": marker,
    }
    monster = {
        "id": "m3",
        "pos": [2000, 0, 0],
        "bag": [],
        "hp": {"current": 100, "max": 100},
        "ions": 60,
        "ions_max": 100,
        "_ai_state": {"pending_pursuit": [2000, 1, 0]},
    }

    rng = FixedRNG(0)

    execute_random_action(monster, ctx, rng=rng)

    assert marker.marked is True
    assert monster["pos"] == [2000, 1, 0]
    assert any(kind == "AI/PURSUIT" and meta["success"] for kind, meta in _turnlog_events)
