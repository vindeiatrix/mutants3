from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services import combat_loot, monster_actions


class _FakeRegistry:
    def __init__(self) -> None:
        self.instances: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, tuple[int, int, int]] = {}
        self._next_id = 0

    def list_instances_at(self, year: int, x: int, y: int) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for iid, pos in self.positions.items():
            if pos == (year, x, y):
                inst = self.instances.get(iid)
                if inst is not None:
                    matches.append(copy.deepcopy(inst))
        return matches

    def get_instance(self, iid: str) -> dict[str, Any] | None:
        inst = self.instances.get(iid)
        return copy.deepcopy(inst) if inst is not None else None

    def mint_instance(self, item_id: str, origin: str) -> str:
        self._next_id += 1
        iid = f"iid-{self._next_id}"
        self.instances[iid] = {"iid": iid, "item_id": item_id, "origin": origin}
        return iid

    def update_instance(self, iid: str, **updates: Any) -> None:
        inst = self.instances.setdefault(iid, {"iid": iid})
        sentinel = getattr(combat_loot.itemsreg, "REMOVE_FIELD", object())
        for key, value in updates.items():
            if value is sentinel:
                inst.pop(key, None)
            else:
                inst[key] = value

        pos = updates.get("pos")
        if isinstance(pos, Mapping):
            try:
                year = int(pos.get("year"))
                x = int(pos.get("x"))
                y = int(pos.get("y"))
            except (TypeError, ValueError):
                return
            self.positions[iid] = (year, x, y)
            return

        try:
            year = int(updates.get("year"))
            x = int(updates.get("x"))
            y = int(updates.get("y"))
        except (TypeError, ValueError):
            return
        self.positions[iid] = (year, x, y)

    def remove_instance(self, iid: str) -> None:
        self.instances.pop(iid, None)
        self.positions.pop(iid, None)


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def push(self, channel: str, message: str, **payload: Any) -> None:
        self.events.append((channel, message, payload))


@pytest.fixture(autouse=True)
def _patch_registry(monkeypatch: pytest.MonkeyPatch) -> _FakeRegistry:
    registry = _FakeRegistry()
    monkeypatch.setattr(combat_loot.itemsreg, "list_instances_at", registry.list_instances_at)
    monkeypatch.setattr(combat_loot.itemsreg, "get_instance", registry.get_instance)
    monkeypatch.setattr(combat_loot.itemsreg, "mint_instance", registry.mint_instance)
    monkeypatch.setattr(combat_loot.itemsreg, "update_instance", registry.update_instance)
    monkeypatch.setattr(combat_loot.itemsreg, "remove_instance", registry.remove_instance)
    return registry


def _catalog() -> dict[str, dict[str, Any]]:
    return {
        "a_item": {"name": "Alpha Blade"},
        "z_item": {"name": "Zee Claw"},
        "armour_plate": {"name": "Plate Armour"},
        "skull": {"name": "Skull"},
    }


def test_drop_monster_loot_sorted_bag_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(combat_loot, "GROUND_CAP", 6)
    catalog = _catalog()
    summary_payload = {
        "bag_drops": [
            {"item_id": "z_item", "iid": "bag-1"},
            {"item_id": "a_item", "iid": "bag-2"},
        ],
        "armour_drop": {"item_id": "armour_plate", "iid": "arm-1"},
    }
    sorted_bag = monster_actions.sorted_bag_drops(summary_payload, catalog=catalog)
    drop_summary: dict[str, Any] = {}
    bus = _Bus()

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(2000, 1, 1),
        bag_entries=None,
        armour_entry=summary_payload["armour_drop"],
        bus=bus,
        catalog=catalog,
        sorted_bag_entries=sorted_bag,
        drop_summary=drop_summary,
    )

    assert [entry["drop_source"] for entry in minted] == ["bag", "bag", "skull", "armour"]
    assert [entry.get("item_id") for entry in minted] == ["a_item", "z_item", "skull", "armour_plate"]
    assert vaporized == []
    assert drop_summary["attempt_order"] == ["bag", "bag", "skull", "armour"]
    assert drop_summary["messages"] == []
    assert drop_summary["pos"] == {"year": 2000, "x": 1, "y": 1}
    assert bus.events == []

    summary_payload["drops_vaporized"] = drop_summary["vaporized"]
    vapor_summary = monster_actions.drop_summary(summary_payload, catalog=catalog)
    assert vapor_summary == {"count": 0, "vaporized": [], "messages": []}


def test_drop_monster_loot_vaporizes_when_ground_full(
    monkeypatch: pytest.MonkeyPatch, _patch_registry: _FakeRegistry
) -> None:
    monkeypatch.setattr(combat_loot, "GROUND_CAP", 1)
    catalog = _catalog()

    existing = combat_loot.itemsreg.mint_instance("rock", "ground")
    combat_loot.itemsreg.update_instance(
        existing,
        item_id="rock",
        pos={"year": 2000, "x": 1, "y": 1},
        year=2000,
        x=1,
        y=1,
    )

    summary_payload = {
        "bag_drops": [
            {"item_id": "z_item", "iid": "bag-1"},
            {"item_id": "a_item", "iid": "bag-2"},
        ],
        "armour_drop": {"item_id": "armour_plate", "iid": "arm-1"},
    }
    sorted_bag = monster_actions.sorted_bag_drops(summary_payload, catalog=catalog)
    drop_summary: dict[str, Any] = {}
    bus = _Bus()

    minted, vaporized = combat_loot.drop_monster_loot(
        pos=(2000, 1, 1),
        bag_entries=None,
        armour_entry=summary_payload["armour_drop"],
        bus=bus,
        catalog=catalog,
        sorted_bag_entries=sorted_bag,
        drop_summary=drop_summary,
    )

    assert minted == []
    assert [entry["drop_source"] for entry in vaporized] == ["bag", "bag", "skull", "armour"]
    assert len(drop_summary["messages"]) == 4
    assert drop_summary["attempt_order"] == ["bag", "bag", "skull", "armour"]
    assert drop_summary["pos"] == {"year": 2000, "x": 1, "y": 1}
    assert all(message.endswith("it vaporizes.") for message in drop_summary["messages"])
    assert len(bus.events) == 4
    assert [event[1] for event in bus.events] == drop_summary["messages"]

    summary_payload["drops_vaporized"] = drop_summary["vaporized"]
    vapor_summary = monster_actions.drop_summary(summary_payload, catalog=catalog)
    assert vapor_summary["count"] == 4
    assert vapor_summary["messages"] == drop_summary["messages"]
