from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

import pytest

from mutants.repl.dispatch import Dispatch
from mutants.services import monster_ai
from mutants.ui.feedback import FeedbackBus


class _DummyMonsters:
    def __init__(self, monsters: Iterable[Mapping[str, Any]]):
        self._monsters = list(monsters)

    def list_at(self, year: int, x: int, y: int) -> List[Mapping[str, Any]]:
        return [
            m
            for m in self._monsters
            if m.get("pos") == [int(year), int(x), int(y)]
        ]


class _DummySink:
    def __init__(self) -> None:
        self.events: List[Dict[str, str]] = []

    def handle(self, event: Dict[str, str]) -> None:
        self.events.append(event)


class _FixedRng:
    def __init__(self, values: Iterable[float]):
        self._values = list(values)
        if not self._values:
            self._values = [0.0]
        self._idx = 0

    def random(self) -> float:
        value = self._values[min(self._idx, len(self._values) - 1)]
        self._idx += 1
        return value


@pytest.fixture
def ctx_base() -> Dict[str, Any]:
    state = {
        "active_id": "player-1",
        "players": [
            {"id": "player-1", "pos": [2000, 3, 4]},
        ],
    }
    bus = FeedbackBus()
    sink = _DummySink()
    return {
        "player_state": state,
        "feedback_bus": bus,
        "logsink": sink,
    }


def _build_dispatch(ctx: Dict[str, Any]) -> Dispatch:
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    dispatch.set_context(ctx)
    return dispatch


def test_monster_tick_executes_actions(monkeypatch: pytest.MonkeyPatch, ctx_base: Dict[str, Any]) -> None:
    ctx = dict(ctx_base)
    monster = {
        "id": "monster-1",
        "pos": [2000, 3, 4],
        "target_player_id": "player-1",
        "hp": {"current": 5, "max": 5},
    }
    ctx["monsters"] = _DummyMonsters([monster])
    ctx["monster_ai_rng"] = _FixedRng([0.1])
    ctx["monster_ai_credit_weights"] = [0.0, 0.0, 1.0, 0.0]

    calls: List[str] = []

    def fake_action(mon: Mapping[str, Any], action_ctx: Mapping[str, Any], *, rng: Any | None = None) -> None:
        calls.append(mon.get("id"))

    monkeypatch.setattr(monster_ai.monster_actions, "execute_random_action", fake_action)

    dispatch = _build_dispatch(ctx)
    dispatch.register("noop", lambda arg: None)

    dispatch.call("noop", "")

    assert calls == ["monster-1", "monster-1"]
    assert ctx["logsink"].events
    kinds = {event["kind"] for event in ctx["logsink"].events}
    assert kinds == {"AI/TICK"}
    texts = [event["text"] for event in ctx["logsink"].events]
    assert any(text.endswith("credits=2") for text in texts)


def test_monster_tick_skips_non_aggro(monkeypatch: pytest.MonkeyPatch, ctx_base: Dict[str, Any]) -> None:
    ctx = dict(ctx_base)
    monsters = [
        {
            "id": "monster-1",
            "pos": [2000, 3, 4],
            "target_player_id": "someone-else",
            "hp": {"current": 5, "max": 5},
        },
        {
            "id": "monster-2",
            "pos": [2000, 3, 4],
            "target_player_id": "player-1",
            "hp": {"current": 0, "max": 5},
        },
        {
            "id": "monster-3",
            "pos": [2000, 2, 4],
            "target_player_id": "player-1",
            "hp": {"current": 5, "max": 5},
        },
        {
            "id": "monster-4",
            "pos": [2000, 3, 4],
            "target_player_id": "player-1",
            "hp": {"current": 5, "max": 5},
        },
    ]
    ctx["monsters"] = _DummyMonsters(monsters)
    ctx["monster_ai_rng"] = _FixedRng([0.9])
    ctx["monster_ai_credit_weights"] = [1.0, 0.0, 0.0, 0.0]

    def fail_action(*_: Any, **__: Any) -> None:
        raise AssertionError("action should not run")

    monkeypatch.setattr(monster_ai.monster_actions, "execute_random_action", fail_action)

    dispatch = _build_dispatch(ctx)

    dispatch.call("unknown", "")  # unresolved command still advances the turn

    events = [event for event in ctx["logsink"].events if event["kind"] == "AI/TICK"]
    assert events == [{"ts": "", "kind": "AI/TICK", "text": "mon=monster-4 credits=0"}]
