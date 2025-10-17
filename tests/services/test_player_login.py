from __future__ import annotations

import random
from typing import Any, Dict, Iterable, Optional

import pytest

from mutants.engine import session
from mutants.services import player_login, random_pool
from mutants.services.random_pool import RandomPool
from mutants.services.turn_scheduler import TurnScheduler


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, kind: str, message: str) -> None:
        self.messages.append((kind, message))


class DummyMonsters:
    def __init__(self, monsters: Iterable[Dict[str, Any]]) -> None:
        self._monsters = [dict(mon) for mon in monsters]
        self.mark_dirty_calls = 0

    def list_at(self, year: int, x: int, y: int) -> Iterable[Dict[str, Any]]:
        return self._monsters

    def get(self, monster_id: str) -> Optional[Dict[str, Any]]:
        for monster in self._monsters:
            ident = str(monster.get("id") or monster.get("instance_id") or "")
            if ident == monster_id:
                return monster
        return None

    def mark_dirty(self) -> None:
        self.mark_dirty_calls += 1


class InMemoryRuntimeKV:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


def test_login_entry_rolls_target_without_attack(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryRuntimeKV()
    pool = RandomPool(store)
    monkeypatch.setattr(random_pool, "_POOL", pool, raising=False)
    monkeypatch.setattr(session, "_TURN_SCHEDULER", None, raising=False)

    tick_logs: list[int] = []

    def fake_emit(context: Any, kind: str, *, message: str | None = None, **meta: Any) -> None:
        if kind == "TURN/TICK":
            tick_logs.append(int(meta.get("tick", 0)))

    ai_calls: list[tuple[str, Optional[str]]] = []

    def fake_on_player_command(context: Any, *, token: str, resolved: Optional[str]) -> None:
        ai_calls.append((token, resolved))

    monkeypatch.setattr("mutants.services.turn_scheduler.turnlog.emit", fake_emit)
    monkeypatch.setattr("mutants.services.monster_ai.on_player_command", fake_on_player_command)

    player_state = {
        "active_id": "player-1",
        "class": "Thief",
        "active": {
            "id": "player-1",
            "class": "Thief",
            "pos": [2000, 1, 2],
            "hp": {"current": 20, "max": 20},
        },
        "players": [
            {
                "id": "player-1",
                "class": "Thief",
                "pos": [2000, 1, 2],
                "hp": {"current": 20, "max": 20},
            }
        ],
        "ready_target_by_class": {"Thief": None},
        "target_monster_id_by_class": {"Thief": None},
    }

    monster_payload = {
        "id": "monster-1",
        "monster_id": "monster-1",
        "name": "Test Monster",
        "pos": [2000, 1, 2],
        "hp": {"current": 5, "max": 5},
        "taunt": "Grr",
        "target_player_id": None,
    }

    monsters = DummyMonsters([monster_payload])

    ctx: Dict[str, Any] = {
        "feedback_bus": DummyBus(),
        "logsink": None,
        "turn_observer": None,
        "session": {},
        "player_state": player_state,
        "monsters": monsters,
    }

    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler
    session.set_turn_scheduler(scheduler)

    rng = random.Random(2)

    result = player_login.handle_login_entry(ctx, rng=rng)

    assert result == {
        "ticks": 1,
        "results": [{"ok": True, "target_set": True, "taunt": "Grr", "woke": True}],
    }

    assert monsters.mark_dirty_calls == 1
    stored_monster = monsters.get("monster-1")
    assert stored_monster and stored_monster["target_player_id"] == "player-1"
    assert player_state["active"]["hp"]["current"] == 20
    assert ("COMBAT/TAUNT", "Grr") in ctx["feedback_bus"].messages
    assert all("strikes you" not in msg for _, msg in ctx["feedback_bus"].messages)
    assert random_pool.get_rng_tick("turn") == 1
    assert tick_logs == [1]
    assert ai_calls == [("login-entry", "login-entry")]

