import copy

import pytest

from mutants.commands import combat, statistics
from mutants.services import player_state as pstate


class Bus:
    def __init__(self) -> None:
        self.msgs: list[tuple[str, str]] = []

    def push(self, kind: str, text: str) -> None:
        self.msgs.append((kind, text))


class MonsterState:
    def __init__(self, monsters: list[dict[str, object]]) -> None:
        self._monsters = monsters

    def list_at(self, year: int, x: int, y: int) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for monster in self._monsters:
            pos = monster.get("pos")
            if isinstance(pos, list) and len(pos) >= 3:
                try:
                    if int(pos[0]) == year and int(pos[1]) == x and int(pos[2]) == y:
                        result.append(monster)
                except (TypeError, ValueError):
                    continue
        return result


def _base_state() -> dict[str, object]:
    stats = {"str": 10, "dex": 12, "int": 8, "wis": 9, "con": 11, "cha": 7}
    hp = {"current": 10, "max": 10}
    player = {
        "id": "p1",
        "name": "Thief",
        "class": "Thief",
        "pos": [2000, 1, 1],
        "stats": dict(stats),
        "hp": dict(hp),
        "inventory": [],
        "bags": {"Thief": []},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "ready_target_by_class": {"Thief": None},
        "ready_target": None,
        "target_monster_id": None,
        "wielded": None,
        "armour": {"wearing": None},
        "ions": 0,
        "Ions": 0,
        "riblets": 0,
        "Riblets": 0,
        "exp_points": 0,
        "level": 1,
        "exhaustion": 0,
    }
    state = {
        "players": [copy.deepcopy(player)],
        "active_id": "p1",
        "active": copy.deepcopy(player),
        "inventory": [],
        "bags": {"Thief": []},
        "equipment_by_class": {"Thief": {"armour": None}},
        "wielded_by_class": {"Thief": None},
        "ready_target_by_class": {"Thief": None},
        "stats_by_class": {"Thief": dict(stats)},
        "hp_by_class": {"Thief": dict(hp)},
        "ions_by_class": {"Thief": 0},
        "riblets_by_class": {"Thief": 0},
        "exp_by_class": {"Thief": 0},
        "level_by_class": {"Thief": 1},
        "bags_by_class": {"Thief": []},
        "stats": dict(stats),
        "hp": dict(hp),
        "ions": 0,
        "Ions": 0,
        "riblets": 0,
        "Riblets": 0,
        "exp_points": 0,
        "level": 1,
        "exhaustion": 0,
        "wielded": None,
        "ready_target": None,
        "target_monster_id": None,
    }
    return state


@pytest.fixture
def command_env(monkeypatch):
    state_store: dict[str, object] = {}

    def fake_load_state() -> dict[str, object]:
        return copy.deepcopy(state_store)

    def fake_save_state(new_state: dict[str, object]) -> None:
        state_store.clear()
        state_store.update(copy.deepcopy(new_state))

    monkeypatch.setattr(pstate, "load_state", fake_load_state)
    monkeypatch.setattr(pstate, "save_state", fake_save_state)

    def setup(*, ready_target: str | None = None) -> None:
        state_store.clear()
        state_store.update(_base_state())
        if ready_target:
            pstate.set_ready_target_for_active(ready_target)

    return {"setup": setup, "state": state_store}


def _ctx(monsters) -> tuple[dict[str, object], Bus]:
    bus = Bus()
    ctx = {"feedback_bus": bus, "monsters": monsters}
    return ctx, bus


def test_combat_sets_ready_target(command_env):
    command_env["setup"]()
    monsters = MonsterState(
        [
            {"id": "ghoul#1", "name": "Ghoul", "hp": {"current": 12, "max": 12}, "pos": [2000, 1, 1]},
            {"id": "ogre#1", "name": "Ogre", "hp": {"current": 20, "max": 20}, "pos": [2000, 2, 2]},
        ]
    )
    ctx, bus = _ctx(monsters)

    result = combat.combat_cmd("gh", ctx)

    assert result["ok"] is True
    assert result["target_id"] == "ghoul#1"
    assert any("ready yourself" in msg for _, msg in bus.msgs)
    assert pstate.get_ready_target_for_active(pstate.load_state()) == "ghoul#1"


def test_combat_clear_command(command_env):
    command_env["setup"]()
    pstate.set_ready_target_for_active("ghoul#1")
    monsters = MonsterState([])
    ctx, bus = _ctx(monsters)

    result = combat.combat_cmd("none", ctx)

    assert result["ok"] is True and result["cleared"] is True
    assert any("lower your guard" in msg for _, msg in bus.msgs)
    assert pstate.get_ready_target_for_active(pstate.load_state()) is None


def test_combat_ignores_dead_monsters(command_env):
    command_env["setup"]()
    monsters = MonsterState(
        [
            {"id": "ghoul#1", "name": "Ghoul", "hp": {"current": 0, "max": 12}, "pos": [2000, 1, 1]}
        ]
    )
    ctx, bus = _ctx(monsters)

    result = combat.combat_cmd("gh", ctx)

    assert result["ok"] is False
    assert any("No living monsters" in msg for _, msg in bus.msgs)
    assert pstate.get_ready_target_for_active(pstate.load_state()) is None


def test_statistics_reports_ready_target(command_env):
    command_env["setup"]()
    pstate.set_ready_target_for_active("ghoul#1")
    monsters = MonsterState(
        [
            {"id": "ghoul#1", "name": "Ghoul", "hp": {"current": 8, "max": 12}, "pos": [2000, 1, 1]}
        ]
    )
    ctx, bus = _ctx(monsters)

    statistics.statistics_cmd("", ctx)

    ready_lines = [text for kind, text in bus.msgs if "Ready to Combat" in text]
    assert ready_lines
    assert ready_lines[0].endswith("Ghoul")


def test_statistics_clears_missing_target(command_env):
    command_env["setup"]()
    pstate.set_ready_target_for_active("ghoul#1")
    monsters = MonsterState([])
    ctx, bus = _ctx(monsters)

    statistics.statistics_cmd("", ctx)

    ready_lines = [text for kind, text in bus.msgs if "Ready to Combat" in text]
    assert ready_lines
    assert ready_lines[0].endswith("NO ONE")
    assert pstate.get_ready_target_for_active(pstate.load_state()) is None
