from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.commands import travel
from mutants.engine import session
from mutants.services import monster_actions, random_pool
from mutants.services.random_pool import RandomPool
import mutants.services.monster_ai as _monster_ai_pkg

sys.modules.setdefault("mutants.services.monster_ai.monster_actions", monster_actions)
from mutants.services.turn_scheduler import TurnScheduler


class DummyBus:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, str]] = []

    def push(self, kind: str, message: str) -> None:
        self.messages.append((kind, message))


class DummyRuntimeKV:
    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


class MonstersStub:
    def __init__(self, monsters: Iterable[MutableMapping[str, Any]]) -> None:
        self._monsters = list(monsters)
        self.dirty = False

    def list_all(self) -> List[MutableMapping[str, Any]]:
        return self._monsters

    def list_at(self, year: int, x: int, y: int) -> List[MutableMapping[str, Any]]:
        result: List[MutableMapping[str, Any]] = []
        for monster in self._monsters:
            pos = monster.get("pos")
            if not isinstance(pos, Iterable):
                continue
            coords = list(pos)
            if len(coords) != 3:
                continue
            try:
                myear, mx, my = int(coords[0]), int(coords[1]), int(coords[2])
            except (TypeError, ValueError):
                continue
            if myear == int(year) and mx == int(x) and my == int(y):
                result.append(monster)
        return result

    def get(self, monster_id: str) -> Optional[MutableMapping[str, Any]]:
        for monster in self._monsters:
            if str(monster.get("id")) == monster_id:
                return monster
        return None

    def mark_dirty(self) -> None:
        self.dirty = True


class DummyWorld:
    def __init__(self, year: int) -> None:
        self.year = int(year)


def _setup_player_state() -> Dict[str, Any]:
    return {
        "active_id": "player-1",
        "players": [
            {"id": "player-1", "pos": [1000, 0, 0], "class": "warrior", "ions": 60000},
        ],
        "active": {"id": "player-1", "pos": [1000, 0, 0], "class": "warrior", "ions": 60000},
        "classes": {"warrior": {"ions": 60000}},
    }


def test_travel_reentry_triggers_immediate_action(monkeypatch: pytest.MonkeyPatch) -> None:
    state_holder = {"state": _setup_player_state()}

    def fake_load_state() -> Dict[str, Any]:
        return copy.deepcopy(state_holder["state"])

    def fake_save_state(new_state: Mapping[str, Any]) -> None:
        state_holder["state"] = copy.deepcopy(new_state)

    def fake_get_active_class(state: Mapping[str, Any]) -> str:
        active = state.get("active")
        if isinstance(active, Mapping) and active.get("class"):
            return str(active.get("class"))
        players = state.get("players")
        if isinstance(players, Iterable):
            for entry in players:
                if isinstance(entry, Mapping) and entry.get("class"):
                    return str(entry.get("class"))
        return "warrior"

    def fake_get_ions_for_active(state: Mapping[str, Any]) -> int:
        cls = fake_get_active_class(state)
        classes = state.get("classes")
        if isinstance(classes, MutableMapping):
            entry = classes.get(cls)
            if isinstance(entry, Mapping) and "ions" in entry:
                return int(entry.get("ions", 0))
        return 0

    def fake_set_ions_for_active(state: MutableMapping[str, Any], new_amount: int) -> int:
        cls = fake_get_active_class(state)
        classes = state.setdefault("classes", {})
        if isinstance(classes, MutableMapping):
            entry = classes.setdefault(cls, {})
            if isinstance(entry, MutableMapping):
                entry["ions"] = int(new_amount)
        active = state.setdefault("active", {})
        if isinstance(active, MutableMapping):
            active["ions"] = int(new_amount)
        base = state_holder["state"]
        classes_base = base.setdefault("classes", {})
        if isinstance(classes_base, MutableMapping):
            entry_base = classes_base.setdefault(cls, {})
            if isinstance(entry_base, MutableMapping):
                entry_base["ions"] = int(new_amount)
        active_base = base.setdefault("active", {})
        if isinstance(active_base, MutableMapping):
            active_base["ions"] = int(new_amount)
        players = base.get("players")
        if isinstance(players, list):
            for entry in players:
                if isinstance(entry, MutableMapping) and entry.get("id") == base.get("active_id"):
                    entry["ions"] = int(new_amount)
        return int(new_amount)

    player_doc: Dict[str, Any] = {
        "pos": [1000, 0, 0],
        "ions": 60000,
        "Ions": 60000,
        "active": {
            "pos": [1000, 0, 0],
            "class": "warrior",
            "ions": 60000,
            "Ions": 60000,
        },
    }

    monkeypatch.setattr(travel.pstate, "load_state", fake_load_state)
    monkeypatch.setattr(travel.pstate, "save_state", fake_save_state)
    monkeypatch.setattr(travel.pstate, "ensure_active_profile", lambda player, ctx: None)
    monkeypatch.setattr(travel.pstate, "bind_inventory_to_active_class", lambda player: None)
    monkeypatch.setattr(travel.pstate, "get_active_class", fake_get_active_class)
    monkeypatch.setattr(travel.pstate, "get_ions_for_active", fake_get_ions_for_active)
    monkeypatch.setattr(travel.pstate, "set_ions_for_active", fake_set_ions_for_active)
    monkeypatch.setattr(travel.pstate, "_pdbg_enabled", lambda: False)
    monkeypatch.setattr(travel.pstate, "_pdbg_setup_file_logging", lambda: None)

    monkeypatch.setattr(travel.itx, "_load_player", lambda: player_doc)
    monkeypatch.setattr(travel.itx, "_ensure_inventory", lambda player: None)

    store = DummyRuntimeKV()
    pool = RandomPool(store)
    monkeypatch.setattr(random_pool, "_POOL", pool, raising=False)
    monkeypatch.setattr(session, "_TURN_SCHEDULER", None, raising=False)

    monster: Dict[str, Any] = {
        "id": "mon-1",
        "name": "Watcher",
        "target_player_id": "player-1",
        "pos": [1000, 0, 0],
        "hp": {"current": 10, "max": 10},
        "_ai_state": {
            "target_positions": {
                "player-1": {"pos": [1000, 0, 0], "co_located": True}
            }
        },
    }
    monsters = MonstersStub([monster])

    ctx: Dict[str, Any] = {
        "feedback_bus": DummyBus(),
        "player_state": copy.deepcopy(state_holder["state"]),
        "monsters": monsters,
        "world_years": lambda: [1000, 2000],
        "world_loader": lambda year: DummyWorld(year),
    }

    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler
    session.set_turn_scheduler(scheduler)

    call_log: List[str] = []

    def fake_execute(mon: Any, context: Any, rng: Any | None = None) -> None:
        call_log.append(str(mon.get("id")))

    monkeypatch.setattr(monster_actions, "execute_random_action", fake_execute)
    monkeypatch.setattr("mutants.services.monster_ai._roll_credits", lambda rng, weights: 0)

    def run_travel(year: int) -> Tuple[str, str]:
        travel.travel_cmd(str(year), ctx)
        return "travel", "travel"

    scheduler.tick(lambda: run_travel(2000))

    targets = monster.get("_ai_state", {}).get("target_positions", {})
    assert isinstance(targets, Mapping)
    assert targets["player-1"]["pos"] == [2000, 0, 0]
    assert targets["player-1"]["co_located"] is False
    assert call_log == []

    scheduler.tick(lambda: run_travel(1000))

    assert call_log == ["mon-1"]
    targets = monster.get("_ai_state", {}).get("target_positions", {})
    assert targets["player-1"]["pos"] == [1000, 0, 0]
    assert targets["player-1"]["co_located"] is True
