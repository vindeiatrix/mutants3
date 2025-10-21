from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any, List

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
        "level": 3,
    }


def _catalog_entry(monster_id: str) -> dict[str, Any]:
    path = Path("state/monsters/catalog.json")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    for entry in catalog:
        if entry.get("monster_id") == monster_id:
            return entry
    raise KeyError(monster_id)


def _context(rng: DummyRNG, config: CombatConfig | None = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "monster_ai_rng": rng,
        "logsink": DummySink(),
        "monster_ai_ground_items": [],
        "monster_ai_player_level": 3,
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


def test_flee_threshold_adjusts_with_level_delta() -> None:
    config = CombatConfig()
    underleveled_monster = _base_monster()
    underleveled_monster["hp"] = {"current": 4, "max": 20}

    # Outlevelled monster gains courage penalty (+5 flee chance).
    ctx_high_player = _context(DummyRNG([0]), config)
    ctx_high_player["monster_ai_player_level"] = underleveled_monster["level"] + 5
    result_high_player = cascade.evaluate_cascade(underleveled_monster, ctx_high_player)

    assert result_high_player.gate == "FLEE"
    assert result_high_player.threshold == config.flee_pct + 5
    assert result_high_player.data.get("level_delta") == 5
    assert result_high_player.data.get("flee_mode") == "hp"

    # Monster significantly higher level loses a bit of flee chance.
    confident_monster = _base_monster()
    confident_monster["hp"] = {"current": 4, "max": 20}
    confident_monster["level"] = 10

    ctx_low_player = _context(DummyRNG([0]), config)
    ctx_low_player["monster_ai_player_level"] = 4
    result_low_player = cascade.evaluate_cascade(confident_monster, ctx_low_player)

    expected_threshold = max(0, config.flee_pct - 5)
    assert result_low_player.threshold == expected_threshold
    assert result_low_player.data.get("level_delta") == -6
    assert result_low_player.data.get("flee_mode") == "hp"


def test_cracked_panic_triggers_extra_flee_check() -> None:
    config = CombatConfig()
    monster = _base_monster()
    monster["hp"] = {"current": 18, "max": 20}
    monster["wielded"] = "w1"
    monster["bag"] = [
        {
            "iid": "w1",
            "item_id": itemsreg.BROKEN_WEAPON_ID,
            "origin": "native",
            "enchant_level": 0,
        }
    ]

    ctx = _context(DummyRNG([0]), config)
    ctx["monster_ai_player_level"] = monster["level"] + 5

    result = cascade.evaluate_cascade(monster, ctx)

    assert result.gate == "FLEE"
    assert result.data.get("flee_mode") == "panic"
    assert result.data.get("hp_pct") == 90
    assert result.threshold == config.flee_pct + config.cracked_flee_bonus + 5


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


def test_species_overrides_from_catalog_adjust_flee_threshold() -> None:
    template = _catalog_entry("junkyard_scrapper")
    config = CombatConfig()
    monster = _base_monster()
    monster.update(
        {
            "monster_id": template["monster_id"],
            "hp": {"current": 2, "max": template["hp_max"]},
            "level": template["level"],
            "template": template,
        }
    )

    result = cascade.evaluate_cascade(monster, _context(DummyRNG([0]), config))

    assert result.gate == "FLEE"
    assert result.threshold == config.flee_pct + 5
    overrides = result.data.get("species_overrides")
    assert overrides and overrides.get("cascade", {}).get("flee_pct") == {"add": 5}


def test_species_overrides_apply_attack_bias_and_prefers_ranged() -> None:
    template = _catalog_entry("rad_swarm_matron")
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=0,
        attack_pct=40,
        pickup_pct=0,
        emote_pct=0,
    )
    monster = _base_monster()
    monster.update(
        {
            "monster_id": template["monster_id"],
            "hp": {"current": template["hp_max"], "max": template["hp_max"]},
            "level": template["level"],
            "template": template,
        }
    )

    result = cascade.evaluate_cascade(monster, _context(DummyRNG([0]), config))

    assert result.gate == "ATTACK"
    assert result.threshold == 35
    overrides = result.data.get("species_overrides")
    assert overrides and overrides.get("prefers_ranged") is True
    assert result.data.get("prefers_ranged_override") is True


def test_species_overrides_increase_attack_for_titan() -> None:
    template = _catalog_entry("titan_of_chrome")
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=0,
        attack_pct=30,
        pickup_pct=0,
        emote_pct=0,
    )
    monster = _base_monster()
    monster.update(
        {
            "monster_id": template["monster_id"],
            "hp": {"current": template["hp_max"], "max": template["hp_max"]},
            "level": template["level"],
            "template": template,
        }
    )

    result = cascade.evaluate_cascade(monster, _context(DummyRNG([0]), config))

    assert result.gate == "ATTACK"
    assert result.threshold == 40
    overrides = result.data.get("species_overrides")
    assert overrides and overrides.get("cascade", {}).get("attack_pct") == {"add": 10}


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


def test_bonus_action_forces_pickup_gate() -> None:
    config = CombatConfig(
        flee_hp_pct=0,
        flee_pct=0,
        heal_pct=0,
        convert_pct=0,
        cast_pct=0,
        attack_pct=0,
        pickup_pct=10,
        emote_pct=0,
    )

    monster = _base_monster()
    monster["hp"] = {"current": 20, "max": 20}

    ctx = _context(DummyRNG([90]), config)
    ctx["monster_ai_ground_items"] = [{"item_id": "shiny-rock", "iid": "loot1"}]

    baseline = cascade.evaluate_cascade(monster, ctx)

    assert baseline.gate == "IDLE"
    assert baseline.data.get("bonus_force_pickup") is False

    forced_ctx = _context(DummyRNG([90]), config)
    forced_ctx["monster_ai_ground_items"] = [{"item_id": "shiny-rock", "iid": "loot1"}]
    forced_ctx["monster_ai_bonus_action"] = {"monster_id": "m1", "force_pickup": True}

    forced = cascade.evaluate_cascade(monster, forced_ctx)

    assert forced.gate == "PICKUP"
    assert forced.action == "pickup"
    assert forced.data.get("bonus_force_pickup") is True
    assert forced.reason.startswith("bonus-force")
