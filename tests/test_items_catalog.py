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
            "spawnable": False,
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
            "spawnable": False,
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
            "spawnable": False,
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
            "spawnable": False,
        }
    ]

    warnings, errors = items_catalog._normalize_items(items)

    assert not errors
    assert any("base_power will become an error" in msg for msg in warnings)
    assert any("poisonous/poison_power will become errors" in msg for msg in warnings)

    entry = items[0]
    assert entry["base_power_melee"] == 9
    assert entry["base_power_bolt"] == 9
    assert entry["poison_melee"] is True
    assert entry["poison_bolt"] is True
    assert entry["poison_melee_power"] == 2
    assert entry["poison_bolt_power"] == 2


def test_normalize_items_requires_spawnable():
    items = [
        {
            "item_id": "mystery_item",
        }
    ]

    _warnings, errors = items_catalog._normalize_items(items)

    assert "mystery_item: spawnable must be explicitly true or false." in errors


def test_normalize_items_warns_on_spawnable_ranged():
    items = [
        {
            "item_id": "laser_pistol",
            "ranged": True,
            "enchantable": False,
            "base_power_melee": 1,
            "base_power_bolt": 5,
            "spawnable": True,
        }
    ]

    warnings, errors = items_catalog._normalize_items(items)

    assert not errors
    assert (
        "laser_pistol: ranged items marked spawnable; ensure this is intentional." in warnings
    )
    assert items[0]["spawnable"] is True
