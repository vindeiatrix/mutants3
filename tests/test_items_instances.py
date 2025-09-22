from __future__ import annotations

from typing import Any, Dict, List

import pytest

from mutants.registries import items_instances


class DummyCatalog:
    def __init__(self, data: Dict[str, Dict[str, Any]]):
        self._data = data

    def get(self, item_id: str):
        return self._data.get(item_id)


def test_create_instance_copies_god_tier_flag(tmp_path):
    registry = items_instances.ItemsInstances(str(tmp_path / "instances.json"), [])
    inst = registry.create_instance({"item_id": "holy_blade", "god_tier": True})

    assert inst["god_tier"] is True
    stored = registry.get(inst["instance_id"])
    assert stored is not None
    assert stored["god_tier"] is True


def test_normalize_instance_defaults_god_tier(tmp_path):
    inst_data = [
        {"instance_id": "axe#1", "item_id": "axe", "god_tier": "no"},
        {"instance_id": "mace#1", "item_id": "mace"},
    ]

    registry = items_instances.ItemsInstances(str(tmp_path / "instances.json"), inst_data)

    first = registry.get("axe#1")
    second = registry.get("mace#1")

    assert first is not None and first["god_tier"] is False
    assert second is not None and second["god_tier"] is False


@pytest.fixture
def _memory_instances(monkeypatch) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []

    def fake_cache() -> List[Dict[str, Any]]:
        return data

    monkeypatch.setattr(items_instances, "_cache", fake_cache)
    monkeypatch.setattr(items_instances, "_save_instances_raw", lambda _: None)

    return data


def test_enchant_blockers_detect_condition_and_level(monkeypatch, _memory_instances):
    _memory_instances.append(
        {
            "iid": "knife#1",
            "instance_id": "knife#1",
            "item_id": "knife",
            "condition": 75,
            "enchant_level": 150,
        }
    )

    monkeypatch.setattr(
        items_instances.items_catalog,
        "load_catalog",
        lambda: DummyCatalog({"knife": {"item_id": "knife"}}),
    )

    blockers = items_instances.enchant_blockers_for("knife#1")

    assert "condition" in blockers
    assert "max_enchant" in blockers
    assert not items_instances.is_enchantable("knife#1")


def test_enchant_blockers_detect_catalog_flags(monkeypatch, _memory_instances):
    _memory_instances.append(
        {
            "iid": "wand#1",
            "instance_id": "wand#1",
            "item_id": "wand",
            "condition": 100,
            "enchant_level": 0,
        }
    )

    template = {
        "item_id": "wand",
        "ranged": True,
        "potion": True,
        "spawnable": True,
        "spell_component": True,
    }

    monkeypatch.setattr(
        items_instances.items_catalog, "load_catalog", lambda: DummyCatalog({"wand": template})
    )

    blockers = items_instances.enchant_blockers_for("wand#1")

    for reason in ("ranged", "potion", "spawnable", "spell_component"):
        assert reason in blockers


def test_enchant_blockers_detect_broken(monkeypatch, _memory_instances):
    _memory_instances.append(
        {
            "iid": "broke#1",
            "instance_id": "broke#1",
            "item_id": items_instances.BROKEN_WEAPON_ID,
        }
    )

    monkeypatch.setattr(
        items_instances.items_catalog, "load_catalog", lambda: DummyCatalog({})
    )

    blockers = items_instances.enchant_blockers_for("broke#1")

    assert "broken" in blockers
    assert "condition" not in blockers
