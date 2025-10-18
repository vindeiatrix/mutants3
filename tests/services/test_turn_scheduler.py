from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from mutants.engine import session
from mutants.repl.dispatch import Dispatch
from mutants.services import random_pool
from mutants.services.random_pool import RandomPool
from mutants.services.turn_scheduler import TurnScheduler
from mutants.services.combat_config import CombatConfig


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[Tuple[str, str, Dict[str, Any]]] = []

    def push(self, kind: str, message: str, **meta: Any) -> None:
        self.messages.append((kind, message, dict(meta)))


class InMemoryRuntimeKV:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


class DummyRNG:
    def __init__(self, rolls: List[int]) -> None:
        self._rolls = list(rolls)

    def randrange(self, stop: int) -> int:
        if not self._rolls:
            raise RuntimeError("no rolls left")
        value = self._rolls.pop(0)
        if stop <= 0:
            return 0
        return value % stop


def test_turn_scheduler_advances_tick_for_each_command(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryRuntimeKV()
    pool = RandomPool(store)
    monkeypatch.setattr(random_pool, "_POOL", pool, raising=False)
    monkeypatch.setattr(session, "_TURN_SCHEDULER", None, raising=False)

    ctx: dict[str, Any] = {
        "feedback_bus": DummyBus(),
        "logsink": None,
        "turn_observer": None,
        "session": {},
    }

    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler
    session.set_turn_scheduler(scheduler)

    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    dispatch.set_context(ctx)

    monster_calls: List[Tuple[str, Optional[str]]] = []

    def fake_on_player_command(context: Any, *, token: str, resolved: Optional[str]) -> None:
        monster_calls.append((token, resolved))

    tick_logs: list[int] = []

    def fake_emit(context: Any, kind: str, *, message: str | None = None, **meta: Any) -> None:
        if kind == "TURN/TICK":
            tick_logs.append(int(meta.get("tick", 0)))

    monkeypatch.setattr("mutants.services.monster_ai.on_player_command", fake_on_player_command)
    monkeypatch.setattr("mutants.services.turn_scheduler.turnlog.emit", fake_emit)

    dispatch.register("ping", lambda arg: None)

    assert random_pool.get_rng_tick("turn") == 0

    dispatch.call("ping", "")
    assert random_pool.get_rng_tick("turn") == 1

    dispatch.call("zzz", "")
    assert random_pool.get_rng_tick("turn") == 2

    dispatch.call("ping", "")
    assert random_pool.get_rng_tick("turn") == 3

    assert monster_calls == [("ping", "ping"), ("zzz", None), ("ping", "ping")]
    assert tick_logs == [1, 2, 3]


def test_free_emote_does_not_advance_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryRuntimeKV()
    pool = RandomPool(store)
    monkeypatch.setattr(random_pool, "_POOL", pool, raising=False)
    monkeypatch.setattr(session, "_TURN_SCHEDULER", None, raising=False)

    ctx: dict[str, Any] = {
        "feedback_bus": DummyBus(),
        "logsink": None,
        "turn_observer": None,
        "session": {},
    }

    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler
    session.set_turn_scheduler(scheduler)

    monster = {"id": "mon-1", "name": "Grue"}

    emote_logs: list[dict[str, Any]] = []
    tick_logs: list[int] = []

    def fake_emit(context: Any, kind: str, *, message: str | None = None, **meta: Any) -> None:
        if kind == "AI/ACT/EMOTE":
            emote_logs.append(dict(meta))
        elif kind == "TURN/TICK":
            tick_logs.append(int(meta.get("tick", 0)))

    def fake_on_player_command(context: Any, *, token: str, resolved: Optional[str]) -> None:
        scheduler.queue_free_emote(monster, gate="IDLE")

    monkeypatch.setattr("mutants.debug.turnlog.emit", fake_emit)
    monkeypatch.setattr("mutants.services.monster_ai.on_player_command", fake_on_player_command)

    assert random_pool.get_rng_tick("turn") == 0

    scheduler.tick(lambda: ("wait", "wait"))

    assert random_pool.get_rng_tick("turn") == 1
    assert tick_logs == [1]
    assert len(emote_logs) == 1
    assert emote_logs[0].get("origin") == "free"


def test_bonus_action_pickup_bias(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx: dict[str, Any] = {}
    scheduler = TurnScheduler(ctx)
    ctx["turn_scheduler"] = scheduler

    monster = {"id": "mon-1"}
    payloads: list[dict[str, Any] | None] = []

    def fake_execute(mon: Any, context: Any, rng: Any | None = None) -> None:
        entry = context.get("monster_ai_bonus_action")
        payloads.append(dict(entry) if isinstance(entry, dict) else entry)

    monkeypatch.setattr("mutants.services.monster_actions.execute_random_action", fake_execute)

    scheduler.queue_bonus_action(monster)
    scheduler._run_free_actions(DummyRNG([10]))

    assert len(payloads) == 1
    assert payloads[0] == {"monster_id": "mon-1", "force_pickup": True, "bonus": True}
    assert "monster_ai_bonus_action" not in ctx

    scheduler.queue_bonus_action(monster)
    scheduler._run_free_actions(DummyRNG([75]))

    assert len(payloads) == 2
    assert payloads[1] == {"monster_id": "mon-1", "force_pickup": False, "bonus": True}
    assert "monster_ai_bonus_action" not in ctx


def test_bonus_action_pickup_bias_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx: dict[str, Any] = {}
    scheduler = TurnScheduler(ctx)
    ctx["combat_config"] = CombatConfig(post_kill_force_pickup_pct=80)
    ctx["turn_scheduler"] = scheduler

    monster = {"id": "mon-1"}
    payloads: list[dict[str, Any] | None] = []

    def fake_execute(mon: Any, context: Any, rng: Any | None = None) -> None:
        entry = context.get("monster_ai_bonus_action")
        payloads.append(dict(entry) if isinstance(entry, dict) else entry)

    monkeypatch.setattr("mutants.services.monster_actions.execute_random_action", fake_execute)

    scheduler.queue_bonus_action(monster)
    scheduler._run_free_actions(DummyRNG([79]))

    assert len(payloads) == 1
    assert payloads[0] == {"monster_id": "mon-1", "force_pickup": True, "bonus": True}
    assert "monster_ai_bonus_action" not in ctx

    scheduler.queue_bonus_action(monster)
    scheduler._run_free_actions(DummyRNG([80]))

    assert len(payloads) == 2
    assert payloads[1] == {"monster_id": "mon-1", "force_pickup": False, "bonus": True}
    assert "monster_ai_bonus_action" not in ctx
