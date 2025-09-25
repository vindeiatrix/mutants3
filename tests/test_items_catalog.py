from __future__ import annotations

from mutants.registries import items_catalog


def test_normalize_items_rejects_enchantable_ranged():
    items = [
        {
            "item_id": "longbow",
            "ranged": True,
            "enchantable": True,
            "base_power_melee": 5,
            "base_power_bolt": 15,
        }
    ]

    _warnings, errors = items_catalog._normalize_items(items)

    assert errors
    assert (
        "longbow: ranged items must declare enchantable: false." in errors
    )


def test_normalize_items_allows_enchantable_for_unflagged_items():
    items = [
        {
            "item_id": "amulet",
            "enchantable": True,
        }
    ]

    warnings, errors = items_catalog._normalize_items(items)

    assert not errors
    assert warnings == []


def test_normalize_items_requires_ranged_base_powers():
    items = [
        {
            "item_id": "ion_wand",
            "ranged": True,
            "enchantable": False,
        }
    ]

    _warnings, errors = items_catalog._normalize_items(items)

    assert errors
    assert (
        "ion_wand: ranged items must define base_power_melee and base_power_bolt." in errors
    )


def test_normalize_items_copies_legacy_power_fields():
    items = [
        {
            "item_id": "ion_wand",
            "ranged": True,
            "enchantable": False,
            "base_power": 9,
            "poisonous": True,
            "poison_power": 2,
        }
    ]

    warnings, errors = items_catalog._normalize_items(items)

    assert not errors
    assert warnings == []

    entry = items[0]
    assert entry["base_power_melee"] == 9
    assert entry["base_power_bolt"] == 9
    assert entry["poison_melee"] is True
    assert entry["poison_bolt"] is True
    assert entry["poison_melee_power"] == 2
    assert entry["poison_bolt_power"] == 2
