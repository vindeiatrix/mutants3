from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pytest

from mutants import env, state
from mutants.bootstrap import lazyinit
from mutants.services import monsters_state, player_state, turn_scheduler
from mutants.services.status_manager import StatusManager


@pytest.fixture
def configure_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    env._CONFIG_LOGGED = False
    return tmp_path


def test_status_manager_player_apply_and_tick(
    configure_state_root: Path,
) -> None:
    lazyinit.ensure_player_state(
        state_dir=str(configure_state_root),
        out_name="playerlivestate.json",
    )

    manager = StatusManager()
    applied = manager.apply("player:Thief", "poison", 2)
    assert applied == [{"status_id": "poison", "duration": 2}]

    state_after = player_state.load_state()
    stored = player_state.get_status_effects_for_class("Thief", state=state_after)
    assert stored == applied

    manager.tick()
    after_tick = player_state.load_state()
    updated = player_state.get_status_effects_for_class("Thief", state=after_tick)
    assert updated == [{"status_id": "poison", "duration": 1}]

    manager.tick()
    final_state = player_state.load_state()
    cleared = player_state.get_status_effects_for_class("Thief", state=final_state)
    assert cleared == []


class _StubMonstersStore:
    def __init__(self) -> None:
        self.records: Dict[str, Dict[str, Any]] = {}
        self.updated: List[Dict[str, Any]] = []

    def snapshot(self) -> Iterable[Dict[str, Any]]:
        return list(self.records.values())

    def replace_all(self, records: Iterable[Dict[str, Any]]) -> None:
        self.records = {rec["instance_id"]: dict(rec) for rec in records if "instance_id" in rec}

    def get(self, mid: str) -> Optional[Dict[str, Any]]:
        record = self.records.get(mid)
        return dict(record) if record is not None else None

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        return self.snapshot()

    def spawn(self, rec: Dict[str, Any]) -> None:
        if "instance_id" not in rec:
            raise KeyError("instance_id")
        self.records[str(rec["instance_id"])] = dict(rec)

    def update_fields(self, mid: str, **fields: Any) -> None:
        record = self.records.setdefault(mid, {"instance_id": mid})
        stats_payload = fields.pop("stats_json", None)
        if isinstance(stats_payload, str):
            try:
                record.update(json.loads(stats_payload))
            except json.JSONDecodeError:
                pass
        for key, value in fields.items():
            record[key] = value
        entry = {"instance_id": mid}
        entry.update(fields)
        if stats_payload is not None:
            entry["stats_json"] = stats_payload
        self.updated.append(entry)

    def delete(self, mid: str) -> None:
        self.records.pop(mid, None)


def test_status_manager_monster_apply_and_expire(
    configure_state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lazyinit.ensure_player_state(
        state_dir=str(configure_state_root),
        out_name="playerlivestate.json",
    )

    store = _StubMonstersStore()
    path = configure_state_root / "monsters" / "instances.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    monster_payload: Dict[str, Any] = {
        "instance_id": "monster-1",
        "id": "monster-1",
        "monster_id": "goblin",
        "name": "Goblin",
        "pos": [2000, 0, 0],
        "hp": {"current": 5, "max": 5},
        "level": 1,
        "stats": {"str": 5, "dex": 5, "con": 5, "int": 5, "wis": 5, "cha": 5},
        "bag": [],
        "armour_slot": None,
    }

    store.spawn(monster_payload)

    instances = monsters_state.monsters_instances.MonstersInstances(
        path, [], store=store
    )
    state_obj = monsters_state.MonstersState(path, [dict(monster_payload)], instances=instances)

    monsters_state.invalidate_cache()
    monkeypatch.setattr(monsters_state, "load_state", lambda path=path: state_obj)

    manager = StatusManager(monster_loader=lambda: state_obj)

    applied = manager.apply("monster:monster-1", "stun", 3)
    assert applied == [{"status_id": "stun", "duration": 3}]
    assert store.updated
    first_update = store.updated[-1]
    assert json.loads(first_update["timers_json"]) == {
        "status_effects": [{"status_id": "stun", "duration": 3}]
    }

    manager.tick()
    mid_update = store.updated[-1]
    assert json.loads(mid_update["timers_json"]) == {
        "status_effects": [{"status_id": "stun", "duration": 2}]
    }

    manager.tick()
    manager.tick()
    final_update = store.updated[-1]
    assert final_update["timers_json"] is None

    monster_entry = state_obj.get("monster-1")
    assert monster_entry is not None
    assert monster_entry.get("status_effects") == []


def test_turn_scheduler_invokes_status_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[int] = []

    class DummyManager:
        def tick(self, amount: int = 1) -> None:
            calls.append(amount)

    monkeypatch.setattr(
        turn_scheduler.random_pool,
        "advance_rng_tick",
        lambda name: 1,
    )
    monkeypatch.setattr(
        turn_scheduler.random_pool,
        "get_rng",
        lambda name: object(),
    )
    monkeypatch.setattr(
        "mutants.services.monster_ai.on_player_command",
        lambda *args, **kwargs: None,
    )

    manager = DummyManager()
    scheduler = turn_scheduler.TurnScheduler({}, status_manager=manager)

    scheduler.tick(lambda: ("token", None))

    assert calls == [1]
