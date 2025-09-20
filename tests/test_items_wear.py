from __future__ import annotations

import pytest

from mutants.registries import items_instances
from mutants.services import items_wear


@pytest.fixture
def in_memory_instances(monkeypatch):
    data = []

    def fake_cache():
        return data

    monkeypatch.setattr(items_instances, "_cache", fake_cache)
    return data


def test_apply_wear_enchanted_noop(in_memory_instances):
    iid = "enchanted_sword#1"
    in_memory_instances.append(
        {
            "iid": iid,
            "item_id": "enchanted_sword",
            "enchanted": "yes",
            "condition": 90,
        }
    )

    result = items_wear.apply_wear(iid, 12)

    assert result == {"cracked": False, "condition": 90}
    inst = items_instances.get_instance(iid)
    assert inst["condition"] == 90
    assert inst["item_id"] == "enchanted_sword"


def test_apply_wear_cracks_and_idempotent(monkeypatch, in_memory_instances):
    iid = "rusty_club#1"
    in_memory_instances.append(
        {
            "iid": iid,
            "item_id": "rusty_club",
            "enchanted": "no",
            "condition": 4,
        }
    )
    monkeypatch.setattr(
        items_instances.items_catalog,
        "load_catalog",
        lambda: {"rusty_club": {"name": "Rusty Club"}},
    )

    cracked = items_wear.apply_wear(iid, 5)

    assert cracked == {"cracked": True, "condition": 0}
    inst = items_instances.get_instance(iid)
    assert inst["item_id"] == items_instances.BROKEN_WEAPON_ID
    assert "condition" not in inst

    again = items_wear.apply_wear(iid, 3)

    assert again == {"cracked": False, "condition": 0}
    assert inst["item_id"] == items_instances.BROKEN_WEAPON_ID
