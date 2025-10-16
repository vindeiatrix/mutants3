from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pytest

from mutants.engine import session
from mutants.repl.dispatch import Dispatch
from mutants.services import random_pool
from mutants.services.random_pool import RandomPool
from mutants.services.turn_scheduler import TurnScheduler


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[Tuple[str, str]] = []

    def push(self, kind: str, message: str) -> None:
        self.messages.append((kind, message))


class InMemoryRuntimeKV:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


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
