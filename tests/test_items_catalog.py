from __future__ import annotations

from mutants.registries import items_catalog


def test_normalize_items_rejects_enchantable_ranged():
    items = [
        {
            "item_id": "longbow",
            "ranged": True,
            "enchantable": True,
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
