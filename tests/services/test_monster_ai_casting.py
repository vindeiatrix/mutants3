from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from mutants.services import monster_actions
from mutants.services.combat_config import CombatConfig
from mutants.ui import textutils


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, Dict[str, Any]]] = []

    def push(self, kind: str, message: str, **meta: Any) -> None:
        self.messages.append((kind, message, dict(meta)))


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
    assert result["spell"] == "Arcane Burst"
    assert result["spell_id"] == "arcane-burst"
    assert isinstance(result["effect"], dict)
    assert result["effect"]["id"] == "arcane-burst"
    assert monster["ions"] == 30 - CombatConfig().spell_cost
    assert monster["_ai_state"]["ledger"]["ions"] == monster["ions"]

    bus = ctx["feedback_bus"]
    assert [m[0] for m in bus.messages[-2:]] == ["COMBAT/SPELL", "COMBAT/SPELL"]
    attempt_kind, attempt_message, attempt_meta = bus.messages[-2]
    success_kind, success_message, success_meta = bus.messages[-1]
    assert attempt_kind == "COMBAT/SPELL"
    assert success_kind == "COMBAT/SPELL"
    expected_attempt = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_SPELL_ATTEMPT,
        monster="Imp",
        spell="Arcane Burst",
    )
    expected_success = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_SPELL_SUCCESS,
        monster="Imp",
        spell="Arcane Burst",
    )
    assert attempt_message == expected_attempt
    assert attempt_meta["template"] == textutils.TEMPLATE_MONSTER_SPELL_ATTEMPT
    assert attempt_meta["phase"] == "attempt"
    assert success_message == expected_success
    assert success_meta["template"] == textutils.TEMPLATE_MONSTER_SPELL_SUCCESS
    assert success_meta["phase"] == "success"
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
    assert result["spell"] == "Arcane Burst"
    assert result["cost"] == expected_cost
    assert monster["ions"] == 40 - expected_cost
    assert monster["_ai_state"]["ledger"]["ions"] == monster["ions"]
    assert result["effect"] is None
    assert result["spell_id"] == "arcane-burst"

    bus = ctx["feedback_bus"]
    assert [m[0] for m in bus.messages[-2:]] == ["COMBAT/SPELL", "COMBAT/SPELL"]
    attempt_kind, attempt_message, attempt_meta = bus.messages[-2]
    failure_kind, failure_message, failure_meta = bus.messages[-1]
    assert attempt_kind == "COMBAT/SPELL"
    assert failure_kind == "COMBAT/SPELL"
    expected_attempt = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_SPELL_ATTEMPT,
        monster="Warlock",
        spell="Arcane Burst",
    )
    expected_failure = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_SPELL_FAILURE,
        monster="Warlock",
        spell="Arcane Burst",
    )
    assert attempt_message == expected_attempt
    assert attempt_meta["phase"] == "attempt"
    assert attempt_meta["template"] == textutils.TEMPLATE_MONSTER_SPELL_ATTEMPT
    assert failure_message == expected_failure
    assert failure_meta["phase"] == "failure"
    assert failure_meta["template"] == textutils.TEMPLATE_MONSTER_SPELL_FAILURE
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
