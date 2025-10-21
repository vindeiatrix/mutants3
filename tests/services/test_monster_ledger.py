from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, MutableMapping, Optional

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants import state
from mutants.bootstrap import lazyinit
from mutants.players import startup as player_startup
from mutants.services import monster_actions, monsters_state, player_state
from mutants.services.combat_config import CombatConfig
from mutants.services.turn_scheduler import TurnScheduler


class _StubMonstersStore:
    def __init__(self) -> None:
        self.records: Dict[str, Dict[str, Any]] = {}
        self.updated: list[Dict[str, Any]] = []

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


@pytest.fixture
def monsters_state_with_store(tmp_path: Path) -> tuple[monsters_state.MonstersState, _StubMonstersStore]:
    lazyinit.ensure_player_state(state_dir=str(tmp_path), out_name="playerlivestate.json")
    path = tmp_path / "monsters" / "instances.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    store = _StubMonstersStore()
    instances = monsters_state.monsters_instances.MonstersInstances(path, [], store=store)

    payload = {
        "instance_id": "monster-1",
        "id": "monster-1",
        "monster_id": "goblin",
        "name": "Goblin",
        "hp": {"current": 5, "max": 5},
        "level": 1,
        "stats": {key: 5 for key in ("str", "dex", "con", "int", "wis", "cha")},
        "bag": [],
        "armour_slot": None,
        "ions": 0,
        "riblets": 0,
    }

    store.spawn(payload)
    normalized = monsters_state.normalize_records([dict(payload)])
    state_obj = monsters_state.MonstersState(path, normalized, instances=instances)
    return state_obj, store


def test_normalize_records_uses_ai_state_ledger() -> None:
    ledger_state = {"ledger": {"ions": 11, "riblets": 4}, "picked_up": ["abc"]}
    raw = {
        "instance_id": "monster-2",
        "monster_id": "orc",
        "name": "Orc",
        "hp": {"current": 10, "max": 10},
        "level": 1,
        "stats": {key: 5 for key in ("str", "dex", "con", "int", "wis", "cha")},
        "bag": [],
        "armour_slot": None,
        "ai_state_json": json.dumps(ledger_state),
    }

    normalized = monsters_state.normalize_records([raw])
    assert len(normalized) == 1
    monster = normalized[0]
    assert monster["ions"] == 11
    assert monster["riblets"] == 4
    assert monster.get("_ai_state", {}).get("ledger") == {"ions": 11, "riblets": 4}
    encoded = json.loads(monster.get("ai_state_json", "{}"))
    assert encoded.get("ledger") == {"ions": 11, "riblets": 4}


def test_monster_state_save_persists_ai_state(monsters_state_with_store: tuple[monsters_state.MonstersState, _StubMonstersStore]) -> None:
    state_obj, store = monsters_state_with_store
    monster = state_obj.get("monster-1")
    assert monster is not None
    monster["ions"] = 9
    monster["riblets"] = 2
    monster["_ai_state"] = {"ledger": {"ions": 9, "riblets": 2}}

    state_obj.mark_dirty()
    state_obj.save()

    assert store.updated, "Expected persisted payload"
    last_update = store.updated[-1]
    assert json.loads(last_update["stats_json"]) ["ions"] == 9
    encoded = last_update.get("ai_state_json")
    assert encoded is not None
    assert json.loads(encoded) == {"ledger": {"ions": 9, "riblets": 2}}


def test_handle_player_death_updates_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)

    lazyinit.ensure_player_state(state_dir=str(tmp_path), out_name="playerlivestate.json")

    base_state = player_state.load_state()

    # Prime the profile with currency, inventory, and a ready target.
    player_state.set_ions_for_active(base_state, 123)
    current_state = player_state.load_state()
    player_state.set_riblets_for_active(current_state, 45)
    current_state = player_state.load_state()
    player_state.set_ready_target_for_active("monster-99")
    current_state = player_state.load_state()

    active = next(
        entry
        for entry in current_state.get("players", [])
        if isinstance(entry, MutableMapping) and entry.get("id") == current_state.get("active_id")
    )

    for scope in (current_state, active):
        scope["inventory"] = ["iid-weapon", "iid-trinket"]
        scope.setdefault("bags", {})["Thief"] = ["iid-weapon", "iid-trinket"]
        scope.setdefault("bags_by_class", {})["Thief"] = ["iid-weapon", "iid-trinket"]
        scope.setdefault("equipment_by_class", {})["Thief"] = {"armour": "iid-armour"}
        scope.setdefault("wielded_by_class", {})["Thief"] = "iid-weapon"
        scope["wielded"] = "iid-weapon"

    current_state.setdefault("ready_target_by_class", {})["Thief"] = "monster-99"
    current_state.setdefault("target_monster_id_by_class", {})["Thief"] = "monster-99"
    active["ready_target"] = "monster-99"
    active["target_monster_id"] = "monster-99"

    player_state.save_state(current_state)
    state_obj, active_obj = player_state.get_active_pair()

    class DummyBus:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def push(self, topic: str, message: str, **kwargs: Any) -> None:
            self.events.append((topic, message))

    class DummyMonsters:
        def __init__(self) -> None:
            self.marked = 0

        def mark_dirty(self) -> None:
            self.marked += 1

    ctx: MutableMapping[str, Any] = {
        "feedback_bus": DummyBus(),
        "monsters": DummyMonsters(),
    }

    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler

    monster: MutableMapping[str, Any] = {
        "id": "monster-3",
        "instance_id": "monster-3",
        "monster_id": "ogre",
        "name": "Ogre",
        "hp": {"current": 8, "max": 8},
        "level": 1,
        "stats": {key: 5 for key in ("str", "dex", "con", "int", "wis", "cha")},
        "bag": [],
        "armour_slot": None,
        "ions": 0,
        "riblets": 0,
    }

    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {})
    monkeypatch.setattr(monster_actions.turnlog, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(monster_actions.combat_loot, "coerce_pos", lambda value: (2000, 0, 0))
    monkeypatch.setattr(monster_actions.combat_loot, "drop_existing_iids", lambda items, pos: [])
    monkeypatch.setattr(monster_actions.combat_loot, "enforce_capacity", lambda pos, drops, bus=None, catalog=None: None)

    monster_actions._handle_player_death(monster, ctx, state_obj, active_obj, ctx["feedback_bus"])

    scheduler._run_free_actions(random.Random())

    updated_state = player_state.load_state()
    ledger = monster.get("_ai_state", {}).get("ledger", {})

    assert ledger == {"ions": 123, "riblets": 45}
    assert monster["ions"] == 123
    assert monster["riblets"] == 45

    assert player_state.get_ions_for_active(updated_state) == player_startup.START_IONS["fresh"]
    assert player_state.get_riblets_for_active(updated_state) == 0
    assert player_state.get_ready_target_for_active(updated_state) is None

    refreshed_active = next(
        entry
        for entry in updated_state.get("players", [])
        if isinstance(entry, MutableMapping) and entry.get("id") == updated_state.get("active_id")
    )

    assert refreshed_active.get("inventory") == []
    assert refreshed_active.get("bags", {}).get("Thief") == []
    assert refreshed_active.get("bags_by_class", {}).get("Thief") == []
    assert refreshed_active.get("equipment_by_class", {}).get("Thief") == {"armour": None}
    assert refreshed_active.get("wielded_by_class", {}).get("Thief") is None
    assert refreshed_active.get("wielded") is None
    assert refreshed_active.get("pos") == [2000, 0, 0]
    hp_block = refreshed_active.get("hp")
    assert isinstance(hp_block, dict)
    assert hp_block["current"] == hp_block["max"]
    assert ctx["monsters"].marked == 1


def test_heal_action_spends_from_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monster: MutableMapping[str, Any] = {
        "id": "monster-4",
        "instance_id": "monster-4",
        "monster_id": "ghost",
        "name": "Ghost",
        "hp": {"current": 2, "max": 10},
        "level": 1,
        "stats": {key: 5 for key in ("str", "dex", "con", "int", "wis", "cha")},
        "bag": [],
        "armour_slot": None,
        "ions": 10,
        "_ai_state": {"ledger": {"ions": 10, "riblets": 0}},
    }

    monkeypatch.setattr(monster_actions.heal_mod, "heal_cost", lambda monster, config=None: 3)
    monkeypatch.setattr(monster_actions.heal_mod, "heal_amount", lambda monster: 4)
    monkeypatch.setattr(monster_actions.turnlog, "emit", lambda *args, **kwargs: None)

    class DummyBus:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def push(self, topic: str, message: str, **kwargs: Any) -> None:
            self.messages.append(message)

    class DummyMonsters:
        def mark_dirty(self) -> None:
            pass

    ctx: MutableMapping[str, Any] = {
        "combat_config": CombatConfig(),
        "feedback_bus": DummyBus(),
        "monsters": DummyMonsters(),
    }

    result = monster_actions._heal_action(monster, ctx, random.Random(0))
    assert result["ok"] is True
    assert result["remaining_ions"] == 7
    assert monster["ions"] == 7
    ledger = monster.get("_ai_state", {}).get("ledger", {})
    assert ledger.get("ions") == 7
    assert result["hp"]["current"] > 2
