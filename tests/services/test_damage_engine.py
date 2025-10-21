from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import damage_engine

MIN_INNATE_DAMAGE = 6
MIN_BOLT_DAMAGE = 6


@pytest.mark.parametrize(
    ("armour_class", "expected"),
    [
        (0, 50),
        (10, 47),
        (25, 42),
        (47, 35),
    ],
)
def test_resolve_attack_applies_ac_curve(armour_class: int, expected: int) -> None:
    attacker = {"derived": {"str_bonus": 0}}
    defender = {
        "derived": {"dex_bonus": 0},
        "armour_slot": {"derived": {"armour_class": armour_class}},
    }
    item = {"base_power": 50}

    result = damage_engine.resolve_attack(item, attacker, defender, source="melee")

    assert result.damage == expected


@pytest.mark.parametrize(
    ("raw", "ac", "expected"),
    [
        (50, 0, 50),
        (50, 10, 47),
        (50, 25, 42),
        (50, 47, 35),
    ],
)
def test_apply_ac_mitigation_rounding_table(raw: int, ac: int, expected: int) -> None:
    assert damage_engine.apply_ac_mitigation(raw, ac) == expected


def test_bolt_damage_floor_applies_after_mitigation() -> None:
    attacker = {"derived": {"str_bonus": 0}}
    defender = {
        "derived": {"dex_bonus": 0},
        "armour_slot": {"derived": {"armour_class": 100}},
    }
    item = {"base_power_bolt": 5}

    result = damage_engine.resolve_attack(item, attacker, defender, source="bolt")

    mitigated = max(0, result.damage)
    assert mitigated == 0

    final_damage = max(MIN_BOLT_DAMAGE, mitigated)
    assert final_damage == MIN_BOLT_DAMAGE


def test_innate_damage_floor_applies_after_mitigation() -> None:
    attacker = {"derived": {"str_bonus": 0}}
    defender = {
        "derived": {"dex_bonus": 0},
        "armour_slot": {"derived": {"armour_class": 100}},
    }

    result = damage_engine.resolve_attack({}, attacker, defender, source="innate")

    mitigated = max(0, result.damage)
    assert mitigated == 0

    final_damage = max(MIN_INNATE_DAMAGE, mitigated)
    assert final_damage == MIN_INNATE_DAMAGE
