from __future__ import annotations

from typing import Any, List

from mutants.registries import items_instances as itemsreg
from mutants.services.combat_config import CombatConfig
from mutants.services.monster_ai import cascade


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
    monster["ions"] = config.heal_cost + 1
    ctx = _context(rng, config)
    ctx["monster_ai_allow_heal"] = True

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "HEAL"
    assert result.action == "heal"
    assert result.roll == 0


def test_evaluate_cascade_cracked_bias_adjusts_threshold() -> None:
    config = CombatConfig()
    rng = DummyRNG([12])
    monster = _base_monster()
    monster["hp"] = {"current": 4, "max": 20}
    monster["wielded"] = "w1"
    monster["bag"] = [
        {
            "iid": "w1",
            "item_id": itemsreg.BROKEN_WEAPON_ID,
            "origin": "native",
            "enchant_level": 0,
        }
    ]
    ctx = _context(rng, config)

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "FLEE"
    assert result.threshold == config.flee_pct + config.cracked_flee_bonus
    assert result.data.get("cracked_weapon") is True
