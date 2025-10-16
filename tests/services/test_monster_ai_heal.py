from __future__ import annotations

import random
from pathlib import Path
import sys
from typing import Any, Dict

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from mutants.services import monster_actions
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai import heal as heal_mod


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


def _base_ctx() -> Dict[str, Any]:
    return {
        "feedback_bus": DummyBus(),
        "monsters": DummyMonsters(),
        "combat_config": CombatConfig(),
    }


def test_monster_heal_restores_hp_and_spends_ions(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "monster-1",
        "name": "Goblin",
        "level": 4,
        "hp": {"current": 10, "max": 40},
    }
    config = CombatConfig()
    cost_before = heal_mod.heal_cost(monster, config)
    monster["ions"] = cost_before + 1_000

    ctx = _base_ctx()
    ctx["combat_config"] = config

    emitted: list[tuple[str, Dict[str, Any]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        emitted.append((kind, dict(meta)))

    monkeypatch.setattr(monster_actions.turnlog, "emit", fake_emit)

    action = monster_actions._ACTION_TABLE["heal"]
    missing_hp = 40 - 10
    heal_amount = heal_mod.heal_amount(monster)
    result = action(monster, ctx, random.Random(0))

    expected_heal = min(heal_amount, missing_hp)
    expected_cost = cost_before

    assert result["ok"] is True
    assert result["healed"] == expected_heal
    assert monster["hp"]["current"] == 10 + expected_heal
    assert monster["ions"] == cost_before + 1_000 - expected_cost

    bus = ctx["feedback_bus"]
    assert bus.messages[-1] == ("COMBAT/INFO", "Goblin's body is glowing!")

    monsters_state = ctx["monsters"]
    assert monsters_state.mark_dirty_calls == 1

    assert any(kind == "AI/ACT/HEAL" for kind, _ in emitted)
    assert any(kind == "COMBAT/HEAL" for kind, _ in emitted)


def test_monster_heal_rejects_when_ions_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "monster-2",
        "name": "Orc",
        "level": 2,
        "hp": {"current": 5, "max": 30},
    }
    config = CombatConfig()
    monster["ions"] = heal_mod.heal_cost(monster, config) - 1

    ctx = _base_ctx()
    ctx["combat_config"] = config

    emitted: list[tuple[str, Dict[str, Any]]] = []

    def fake_emit(local_ctx, kind: str, **meta):
        emitted.append((kind, dict(meta)))

    monkeypatch.setattr(monster_actions.turnlog, "emit", fake_emit)

    action = monster_actions._ACTION_TABLE["heal"]
    result = action(monster, ctx, random.Random(0))

    assert result["ok"] is False
    assert result["reason"] == "insufficient_ions"
    assert monster["hp"]["current"] == 5
    assert monster["ions"] == heal_mod.heal_cost(monster, config) - 1
    assert not ctx["feedback_bus"].messages
    assert ctx["monsters"].mark_dirty_calls == 0
    assert emitted == []
