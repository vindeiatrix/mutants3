from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from mutants.services import monster_actions
from mutants.services.combat_config import CombatConfig


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, kind: str, message: str) -> None:
        self.messages.append((kind, message))


class DummyMonsters:
    def __init__(self) -> None:
        self.mark_dirty_calls = 0

    def mark_dirty(self) -> None:
        self.mark_dirty_calls += 1


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


def _base_ctx() -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "feedback_bus": DummyBus(),
        "monsters": DummyMonsters(),
        "combat_config": CombatConfig(),
    }
    return ctx


def test_cast_action_success_spends_full_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "caster-1",
        "name": "Imp",
        "ions": 30,
        "_ai_state": {"ledger": {"ions": 30}},
    }

    ctx = _base_ctx()
    ctx["monster_ai_rng"] = DummyRNG([10])

    emitted: list[tuple[str, Dict[str, Any]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        emitted.append((kind, dict(meta)))

    monkeypatch.setattr(monster_actions.turnlog, "emit", fake_emit)

    action = monster_actions._ACTION_TABLE["cast"]
    result = action(monster, ctx, ctx["monster_ai_rng"])

    assert result["ok"] is True
    assert result["cast"] is True
    assert result["cost"] == CombatConfig().spell_cost
    assert monster["ions"] == 30 - CombatConfig().spell_cost
    assert monster["_ai_state"]["ledger"]["ions"] == monster["ions"]

    bus = ctx["feedback_bus"]
    assert bus.messages[-1][1].endswith("unleashes crackling energy!")
    assert ctx["monsters"].mark_dirty_calls == 1
    assert any(kind == "AI/ACT/CAST" for kind, _ in emitted)
    assert any(kind == "COMBAT/CAST" for kind, _ in emitted)


def test_cast_action_failure_costs_half(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "caster-2",
        "name": "Warlock",
        "ions": 40,
        "_ai_state": {"ledger": {"ions": 40}},
    }

    ctx = _base_ctx()
    ctx["monster_ai_rng"] = DummyRNG([99])

    emitted: list[tuple[str, Dict[str, Any]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        emitted.append((kind, dict(meta)))

    monkeypatch.setattr(monster_actions.turnlog, "emit", fake_emit)

    action = monster_actions._ACTION_TABLE["cast"]
    result = action(monster, ctx, ctx["monster_ai_rng"])

    expected_cost = CombatConfig().spell_cost // 2
    assert result["ok"] is False
    assert result["cast"] is False
    assert result["reason"] == "failed_roll"
    assert result["cost"] == expected_cost
    assert monster["ions"] == 40 - expected_cost
    assert monster["_ai_state"]["ledger"]["ions"] == monster["ions"]

    bus = ctx["feedback_bus"]
    assert bus.messages[-1][1].endswith("spell fizzles out.")
    assert ctx["monsters"].mark_dirty_calls == 1
    assert any(kind == "AI/ACT/CAST" for kind, _ in emitted)
    assert any(kind == "COMBAT/CAST" for kind, _ in emitted)


def test_cast_action_aborts_when_ions_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "caster-3",
        "name": "Mage",
        "ions": 5,
        "_ai_state": {"ledger": {"ions": 5}},
    }

    ctx = _base_ctx()
    ctx["monster_ai_rng"] = DummyRNG([0])

    emitted: list[tuple[str, Dict[str, Any]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        emitted.append((kind, dict(meta)))

    monkeypatch.setattr(monster_actions.turnlog, "emit", fake_emit)

    action = monster_actions._ACTION_TABLE["cast"]
    result = action(monster, ctx, ctx["monster_ai_rng"])

    assert result["ok"] is False
    assert result["reason"] == "insufficient_ions"
    assert monster["ions"] == 5
    bus = ctx["feedback_bus"]
    assert isinstance(bus, DummyBus)
    assert bus.messages == []
    assert ctx["monsters"].mark_dirty_calls == 0
    assert emitted == []
