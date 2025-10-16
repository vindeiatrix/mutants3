from __future__ import annotations

import random
from typing import Any, List

import pytest

from mutants.services.combat_config import CombatConfig
from mutants.services import monster_ai
from mutants.services.monster_ai import wake as wake_mod
from mutants.services import monster_actions


class DummyRNG:
    def __init__(self, rolls: List[int]) -> None:
        self._rolls = list(rolls)

    def randrange(self, stop: int) -> int:
        assert stop == 100
        if not self._rolls:
            raise RuntimeError("no rolls left")
        return self._rolls.pop(0)


class DummyMonsters:
    def __init__(self, monsters: List[dict[str, Any]]) -> None:
        self._monsters = monsters

    def list_at(self, year: int, x: int, y: int) -> List[dict[str, Any]]:
        return list(self._monsters)


def _player_state_stub() -> dict[str, Any]:
    return {
        "active_id": "p1",
        "pos": [2000, 1, 1],
        "players": [
            {
                "id": "p1",
                "pos": [2000, 1, 1],
            }
        ],
    }


def _monster_stub() -> dict[str, Any]:
    return {
        "id": "m1",
        "pos": [2000, 1, 1],
        "hp": {"current": 10, "max": 10},
        "target_player_id": "p1",
    }


def test_should_wake_default_thresholds() -> None:
    config = CombatConfig()
    monster = {}

    assert wake_mod.should_wake(monster, "LOOK", DummyRNG([14]), config)
    assert not wake_mod.should_wake(monster, "LOOK", DummyRNG([15]), config)
    assert wake_mod.should_wake(monster, "ENTRY", DummyRNG([9]), config)
    assert not wake_mod.should_wake(monster, "ENTRY", DummyRNG([10]), config)


def test_should_wake_monster_override() -> None:
    config = CombatConfig(wake_on_entry=5)
    monster = {"wake_on_entry": 80}

    assert wake_mod.should_wake(monster, "ENTRY", DummyRNG([79]), config)
    assert not wake_mod.should_wake(monster, "ENTRY", DummyRNG([80]), config)


def test_should_wake_unknown_event_returns_true() -> None:
    config = CombatConfig()
    monster: dict[str, Any] = {}

    assert wake_mod.should_wake(monster, "UNKNOWN", DummyRNG([0]), config)


def test_roll_entry_target_skips_when_wake_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _player_state_stub()
    monster = _monster_stub()
    monster.pop("target_player_id")

    called: list[str] = []

    def fake_should_wake(mon: Any, event: str, rng: Any, config: CombatConfig | None) -> bool:
        called.append(event)
        return False

    monkeypatch.setattr(monster_actions, "_should_wake", fake_should_wake)

    outcome = monster_actions.roll_entry_target(monster, state, random.Random(0))

    assert called == ["ENTRY"]
    assert outcome == {"ok": True, "target_set": False, "taunt": None, "woke": False}
    assert monster.get("target_player_id") is None


def test_roll_entry_target_sets_target_on_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _player_state_stub()
    monster = _monster_stub()
    monster.pop("target_player_id")
    monster["taunt"] = "Roar!"

    monkeypatch.setattr(monster_actions, "_should_wake", lambda *args, **kwargs: True)

    outcome = monster_actions.roll_entry_target(monster, state, random.Random(0))

    assert outcome == {"ok": True, "target_set": True, "taunt": "Roar!", "woke": True}
    assert monster.get("target_player_id") == "p1"


def test_roll_entry_target_skips_wake_when_already_targeted(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _player_state_stub()
    monster = _monster_stub()
    monster["target_player_id"] = "p1"

    def _should_not_run(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("wake should not run when target unchanged")

    monkeypatch.setattr(monster_actions, "_should_wake", _should_not_run)

    outcome = monster_actions.roll_entry_target(monster, state, random.Random(0))

    assert outcome == {"ok": True, "target_set": False, "taunt": None, "woke": True}


def test_on_player_command_uses_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = _monster_stub()
    monsters = DummyMonsters([monster])
    ctx = {
        "monsters": monsters,
        "player_state": _player_state_stub(),
        "monster_ai_rng": random.Random(0),
    }

    wake_calls: list[str] = []

    def fake_should_wake(mon: Any, event: str, rng: Any, config: CombatConfig | None) -> bool:
        wake_calls.append(event)
        return False

    monkeypatch.setattr(wake_mod, "should_wake", fake_should_wake)
    monkeypatch.setattr(monster_ai, "should_wake", fake_should_wake)
    monkeypatch.setattr(monster_actions, "execute_random_action", lambda *args, **kwargs: None)

    monster_ai.on_player_command(ctx, token="LOOK", resolved="look")

    assert wake_calls == ["LOOK"]


def test_on_player_command_entry_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = _monster_stub()
    monsters = DummyMonsters([monster])
    ctx = {
        "monsters": monsters,
        "player_state": _player_state_stub(),
        "monster_ai_rng": random.Random(0),
    }

    wake_calls: list[str] = []

    def fake_should_wake(mon: Any, event: str, rng: Any, config: CombatConfig | None) -> bool:
        wake_calls.append(event)
        return False

    monkeypatch.setattr(wake_mod, "should_wake", fake_should_wake)
    monkeypatch.setattr(monster_ai, "should_wake", fake_should_wake)
    monkeypatch.setattr(monster_actions, "execute_random_action", lambda *args, **kwargs: None)

    monster_ai.on_player_command(ctx, token="login-entry", resolved="login-entry")

    assert wake_calls == ["ENTRY"]
