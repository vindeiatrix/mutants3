from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

import pytest

from mutants.registries import items_instances


class DummyCatalog:
    def __init__(self, data: Dict[str, Dict[str, Any]]):
        self._data = data

    def get(self, item_id: str):
        return self._data.get(item_id)


def test_create_instance_copies_god_tier_flag(monkeypatch, memory_registry):
    memory_registry([])

    monkeypatch.setattr(
        items_instances.items_catalog,
        "load_catalog",
        lambda: DummyCatalog({"holy_blade": {"item_id": "holy_blade", "god_tier": True}}),
    )

    iid = items_instances.mint_instance("holy_blade", origin="debug")
    inst = items_instances.get_instance(iid)

    assert inst is not None
    assert inst["god_tier"] is True


def test_normalize_instance_defaults_god_tier(memory_registry):
    memory_registry(
        [
            {"iid": "axe#1", "instance_id": "axe#1", "item_id": "axe", "god_tier": "no"},
            {"iid": "mace#1", "instance_id": "mace#1", "item_id": "mace"},
        ]
    )

    first = items_instances.get_instance("axe#1")
    second = items_instances.get_instance("mace#1")

    assert first is not None and first["god_tier"] is False
    assert second is not None and second["god_tier"] is False


@pytest.fixture
def memory_registry(monkeypatch):
    data: List[Dict[str, Any]] = []

    def fake_load() -> List[Dict[str, Any]]:
        return data

    def fake_save(raw: List[Dict[str, Any]]) -> None:
        data[:] = list(raw)
        items_instances.invalidate_cache()

    monkeypatch.setattr(items_instances, "_load_instances_raw", fake_load)
    monkeypatch.setattr(items_instances, "_save_instances_raw", fake_save)

    def seed(instances: Iterable[Dict[str, Any]]) -> None:
        data[:] = [dict(inst) for inst in instances]
        items_instances.invalidate_cache()

    items_instances.invalidate_cache()
    return seed


def test_enchant_blockers_no_longer_block_enchantments(memory_registry):
    memory_registry(
        [
            {
                "iid": "knife#1",
                "instance_id": "knife#1",
                "item_id": "knife",
                "condition": 75,
                "enchant_level": 150,
            }
        ]
    )

    blockers = items_instances.enchant_blockers_for("knife#1")

    assert blockers == []
    assert items_instances.is_enchantable("knife#1")


def test_enchant_blockers_only_flag_missing_instances(memory_registry):
    memory_registry([])

    assert items_instances.enchant_blockers_for("missing") == ["missing_instance"]
    assert not items_instances.is_enchantable("missing")


def test_is_enchantable_when_catalog_allows(monkeypatch, memory_registry):
    memory_registry(
        [
            {
                "iid": "hammer#1",
                "instance_id": "hammer#1",
                "item_id": "hammer",
                "condition": 100,
                "enchant_level": 0,
            }
        ]
    )

    template = {"item_id": "hammer", "enchantable": True}

    monkeypatch.setattr(
        items_instances.items_catalog,
        "load_catalog",
        lambda: DummyCatalog({"hammer": template}),
    )

    blockers = items_instances.enchant_blockers_for("hammer#1")

    assert blockers == []
    assert items_instances.is_enchantable("hammer#1")


def test_load_instances_raises_on_duplicate_iids(tmp_path, monkeypatch):
    payload = [
        {"iid": "dup", "instance_id": "dup", "item_id": "axe"},
        {"iid": "dup", "instance_id": "dup", "item_id": "axe"},
    ]
    path = tmp_path / "instances.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(items_instances, "STRICT_DUP_IIDS", True)

    with pytest.raises(ValueError):
        items_instances.load_instances(str(path))


def test_public_crud_api_happy_path(memory_registry):
    memory_registry([])
    iid = items_instances.mint_instance("sword", "loot_drop")

    created = items_instances.get_instance(iid)
    assert created is not None
    assert created["item_id"] == "sword"

    items_instances.update_instance(
        iid,
        enchant_level=5,
        enchanted="yes",
        condition=42,
        notes="shiny",
    )

    updated = items_instances.get_instance(iid)
    assert updated is not None
    assert updated["enchant_level"] == 5
    assert updated["condition"] == 42
    assert updated["notes"] == "shiny"

    items_instances.update_instance(iid, notes=items_instances.REMOVE_FIELD)
    assert "notes" not in items_instances.get_instance(iid)

    moved = items_instances.move_instance(iid, dest=(5, 6, 7))
    assert moved is True
    assert items_instances.get_instance(iid)["pos"] == {"year": 5, "x": 6, "y": 7}

    removed = items_instances.remove_instance(iid)
    assert removed is True
    assert items_instances.get_instance(iid) is None


def test_bulk_add_generates_ids(memory_registry):
    memory_registry([])
    ids = items_instances.bulk_add([{ "item_id": "axe" }])
    assert len(ids) == 1
    inst = items_instances.get_instance(ids[0])
    assert inst is not None
    assert inst["item_id"] == "axe"


def test_move_instance_respects_source(memory_registry):
    memory_registry([])
    iid = items_instances.mint_instance("axe", "spawn")
    items_instances.update_instance(
        iid,
        pos={"year": 1, "x": 2, "y": 3},
        year=1,
        x=2,
        y=3,
    )

    assert items_instances.move_instance(iid, src=(9, 9, 9), dest=(4, 4, 4)) is False
    inst = items_instances.get_instance(iid)
    assert inst is not None
    assert inst["pos"] == {"year": 1, "x": 2, "y": 3}

    assert items_instances.move_instance(iid, src=(1, 2, 3), dest=(4, 4, 4)) is True
    moved = items_instances.get_instance(iid)
    assert moved is not None
    assert moved["pos"] == {"year": 4, "x": 4, "y": 4}
