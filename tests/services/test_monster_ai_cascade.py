from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, List

import math

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.registries import items_instances as itemsreg
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai import cascade
from mutants.services.monster_ai import heal as heal_mod


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


class DummySink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def handle(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _base_monster() -> dict[str, Any]:
    return {
        "id": "m1",
        "hp": {"current": 10, "max": 20},
        "bag": [],
        "ions": 0,
        "pos": (2000, 1, 1),
    }


def _context(rng: DummyRNG, config: CombatConfig | None = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "monster_ai_rng": rng,
        "logsink": DummySink(),
        "monster_ai_ground_items": [],
    }
    if config is not None:
        ctx["combat_config"] = config
    return ctx


def test_evaluate_cascade_priority_order() -> None:
    config = CombatConfig()
    rng = DummyRNG([0])
    monster = _base_monster()
    monster["hp"] = {"current": 4, "max": 20}
    ctx = _context(rng, config)

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "FLEE"
    assert result.action == "flee"
    assert result.roll == 0
    sink = ctx["logsink"]
    assert isinstance(sink, DummySink)
    assert sink.events[-1]["kind"] == "AI/GATE"


def test_evaluate_cascade_rollover_to_heal() -> None:
    config = CombatConfig()
    rng = DummyRNG([99, 0])
    monster = _base_monster()
    monster["hp"] = {"current": 4, "max": 20}
    monster["level"] = 3
    monster["ions"] = heal_mod.heal_cost(monster, config) + 1
    ctx = _context(rng, config)
    ctx["monster_ai_allow_heal"] = True

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "HEAL"
    assert result.action == "heal"
    assert result.roll == 0


def test_evaluate_cascade_cracked_bias_adjusts_threshold() -> None:
    config = CombatConfig()

    # Baseline without a cracked weapon.
    monster = _base_monster()
    monster["hp"] = {"current": 4, "max": 20}
    ctx = _context(DummyRNG([0]), config)

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "FLEE"
    assert result.threshold == config.flee_pct
    assert result.data.get("cracked_weapon") is False

    # Cracked weapon biases the flee gate upward.
    cracked_monster = _base_monster()
    cracked_monster["hp"] = {"current": 4, "max": 20}
    cracked_monster["wielded"] = "w1"
    cracked_monster["bag"] = [
        {
            "iid": "w1",
            "item_id": itemsreg.BROKEN_WEAPON_ID,
            "origin": "native",
            "enchant_level": 0,
        }
    ]
    cracked_ctx = _context(DummyRNG([0]), config)

    cracked_result = cascade.evaluate_cascade(cracked_monster, cracked_ctx)

    assert cracked_result.gate == "FLEE"
    assert cracked_result.threshold == config.flee_pct + config.cracked_flee_bonus
    assert cracked_result.data.get("cracked_weapon") is True


def test_cracked_weapon_halves_attack_weight_only_when_equipped() -> None:
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=0,
        attack_pct=60,
        pickup_pct=0,
        emote_pct=0,
    )

    # No cracked weapon keeps the base attack threshold.
    monster = _base_monster()
    monster["hp"] = {"current": 20, "max": 20}
    ctx = _context(DummyRNG([0]), config)

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "ATTACK"
    assert result.threshold == config.attack_pct
    assert result.data.get("cracked_weapon") is False

    # Cracked weapon halves the attack chance.
    cracked_monster = _base_monster()
    cracked_monster["hp"] = {"current": 20, "max": 20}
    cracked_monster["wielded"] = "w1"
    cracked_monster["bag"] = [
        {
            "iid": "w1",
            "item_id": itemsreg.BROKEN_WEAPON_ID,
            "origin": "native",
            "enchant_level": 0,
        }
    ]
    cracked_ctx = _context(DummyRNG([0]), config)

    cracked_result = cascade.evaluate_cascade(cracked_monster, cracked_ctx)

    assert cracked_result.gate == "ATTACK"
    assert cracked_result.threshold == config.attack_pct // 2
    assert cracked_result.data.get("cracked_weapon") is True


def test_convert_gate_requires_tracked_pickup() -> None:
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=100,
        cast_pct=0,
        attack_pct=0,
        pickup_pct=0,
        emote_pct=0,
    )

    monster = _base_monster()
    monster["hp"] = {"current": 20, "max": 20}
    monster["ions"] = 0
    monster["ions_max"] = 100
    monster["bag"] = [
        {"iid": "loot1", "item_id": "ion-stick", "origin": "world", "enchant_level": 0}
    ]

    ctx = _context(DummyRNG([0]), config)

    result_without_tracking = cascade.evaluate_cascade(monster, ctx)

    assert result_without_tracking.gate == "IDLE"
    assert result_without_tracking.data.get("convertible_loot") is False

    monster["_ai_state"] = {"picked_up": ["loot1"]}
    ctx_tracked = _context(DummyRNG([0]), config)

    result_with_tracking = cascade.evaluate_cascade(monster, ctx_tracked)

    assert result_with_tracking.gate == "CONVERT"
    assert result_with_tracking.action == "convert"
    assert result_with_tracking.data.get("convertible_loot") is True


def test_low_ion_convert_bonus_enables_gate() -> None:
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=0,
        attack_pct=0,
        pickup_pct=0,
        emote_pct=0,
    )

    monster = _base_monster()
    monster["ions"] = 10
    monster["ions_max"] = 100
    monster["bag"] = [
        {"iid": "loot1", "item_id": "ion-stick", "origin": "world", "enchant_level": 0}
    ]
    monster["_ai_state"] = {"picked_up": ["loot1"]}

    ctx = _context(DummyRNG([0]), config)

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "CONVERT"
    assert result.threshold == 10
    assert result.data.get("low_ions") is True


def test_low_ion_cast_threshold_reduction() -> None:
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=50,
        attack_pct=0,
        pickup_pct=0,
        emote_pct=0,
    )

    monster = _base_monster()
    monster["ions"] = config.spell_cost
    monster["ions_max"] = config.spell_cost * 10

    ctx = _context(DummyRNG([0]), config)

    result = cascade.evaluate_cascade(monster, ctx)

    expected_threshold = math.floor(config.cast_pct * 0.6)
    assert result.gate == "CAST"
    assert result.threshold == expected_threshold
