from __future__ import annotations

from typing import Any, List

import pytest

from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services.monster_ai import attack_selection


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


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    catalog = {
        "melee_sword": {"ranged": False, "armour": False},
        "ranged_bow": {"ranged": True, "armour": False},
        itemsreg.BROKEN_WEAPON_ID: {"ranged": False, "armour": False},
    }
    monkeypatch.setattr(items_catalog, "load_catalog", lambda: catalog)
    return catalog


def _monster_with_items(*entries: dict[str, Any]) -> dict[str, Any]:
    bag = [dict(entry) for entry in entries]
    wielded = None
    if bag:
        wielded = bag[0].get("iid")
    return {
        "bag": bag,
        "wielded": wielded,
        "innate_attack": {"name": "Claw"},
    }


def test_select_attack_melee_only_rolls_between_melee_and_innate() -> None:
    monster = _monster_with_items({"iid": "m1", "item_id": "melee_sword", "origin": "native"})
    rng = DummyRNG([0, 96])
    ctx = {"monster_ai_rng": rng}

    plan_melee = attack_selection.select_attack(monster, ctx)
    plan_innate = attack_selection.select_attack(monster, ctx)

    assert plan_melee.source == "melee"
    assert plan_melee.item_iid == "m1"
    assert plan_innate.source == "innate"
    assert plan_innate.item_iid is None


def test_select_attack_ranged_only_honours_prefers_hint() -> None:
    monster = _monster_with_items({"iid": "r1", "item_id": "ranged_bow", "origin": "native"})
    rng = DummyRNG([0, 95])
    ctx = {"monster_ai_rng": rng, "monster_ai_prefers_ranged": True}

    plan_ranged = attack_selection.select_attack(monster, ctx)
    plan_innate = attack_selection.select_attack(monster, ctx)

    assert plan_ranged.source == "bolt"
    assert plan_ranged.item_iid == "r1"
    assert plan_innate.source == "innate"


def test_select_attack_melee_and_ranged_mix_defaults() -> None:
    monster = _monster_with_items(
        {"iid": "m1", "item_id": "melee_sword", "origin": "native"},
        {"iid": "r1", "item_id": "ranged_bow", "origin": "native"},
    )
    rng = DummyRNG([65, 85, 95])
    ctx = {"monster_ai_rng": rng}

    plan_melee = attack_selection.select_attack(monster, ctx)
    plan_ranged = attack_selection.select_attack(monster, ctx)
    plan_innate = attack_selection.select_attack(monster, ctx)

    assert plan_melee.source == "melee"
    assert plan_melee.item_iid == "m1"
    assert plan_ranged.source == "bolt"
    assert plan_ranged.item_iid == "r1"
    assert plan_innate.source == "innate"


def test_select_attack_prefers_ranged_swaps_bias() -> None:
    monster = _monster_with_items(
        {"iid": "m1", "item_id": "melee_sword", "origin": "native"},
        {"iid": "r1", "item_id": "ranged_bow", "origin": "native"},
    )
    monster["prefers_ranged"] = True

    bolt_plan = attack_selection.select_attack(monster, {"monster_ai_rng": DummyRNG([25])})
    melee_plan = attack_selection.select_attack(monster, {"monster_ai_rng": DummyRNG([5])})

    assert bolt_plan.source == "bolt"
    assert bolt_plan.item_iid == "r1"
    assert melee_plan.source == "melee"


def test_select_attack_cracked_melee_halves_weight() -> None:
    monster = _monster_with_items(
        {
            "iid": "m1",
            "item_id": itemsreg.BROKEN_WEAPON_ID,
            "origin": "native",
            "enchant_level": 0,
        },
        {"iid": "r1", "item_id": "ranged_bow", "origin": "native"},
    )
    monster["wielded"] = "m1"

    plan_ranged = attack_selection.select_attack(monster, {"monster_ai_rng": DummyRNG([40])})
    plan_melee = attack_selection.select_attack(monster, {"monster_ai_rng": DummyRNG([10])})

    assert plan_ranged.source == "bolt"
    assert plan_ranged.item_iid == "r1"
    assert plan_melee.source == "melee"

