from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.commands import strike  # noqa: E402
from mutants.services import items_wear  # noqa: E402
from mutants.services import monster_actions  # noqa: E402
from mutants.registries import items_instances as itemsreg  # noqa: E402


class DummyInstances:
    def __init__(self, iid: str, item_id: str) -> None:
        self.iid = iid
        self.item_id = item_id
        self.instances: dict[str, dict[str, object]] = {}
        self.reset()

    def reset(self) -> None:
        self.instances[self.iid] = {
            "iid": self.iid,
            "item_id": self.item_id,
            "condition": 100,
            "enchant_level": 0,
        }

    def get_instance(self, iid: str) -> dict[str, object] | None:
        return self.instances.get(iid)

    def get_condition(self, iid: str) -> int:
        inst = self.instances.get(iid)
        if not inst:
            return 0
        return int(inst.get("condition", 0) or 0)

    def is_enchanted(self, iid: str) -> bool:
        return False

    def set_condition(self, iid: str, value: int) -> int:
        inst = self.instances[iid]
        inst["condition"] = max(0, int(value))
        return int(inst["condition"])

    def crack_instance(self, iid: str) -> dict[str, object]:
        inst = self.instances[iid]
        inst["item_id"] = itemsreg.BROKEN_WEAPON_ID
        inst.pop("condition", None)
        return inst


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str, **_kwargs: object) -> None:
        self.messages.append((channel, message))


@pytest.fixture(autouse=True)
def patch_turnlog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strike.turnlog, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(monster_actions.turnlog, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(monster_actions, "_refresh_monster", lambda monster: None)
    monkeypatch.setattr(monster_actions, "_mark_monsters_dirty", lambda ctx: None)


@pytest.fixture
def dummy_instances(monkeypatch: pytest.MonkeyPatch) -> DummyInstances:
    tracker = DummyInstances("iid-test-weapon", "test_sword")

    monkeypatch.setattr(items_wear.items_instances, "get_instance", tracker.get_instance)
    monkeypatch.setattr(items_wear.items_instances, "get_condition", tracker.get_condition)
    monkeypatch.setattr(items_wear.items_instances, "is_enchanted", tracker.is_enchanted)
    monkeypatch.setattr(items_wear.items_instances, "set_condition", tracker.set_condition)
    monkeypatch.setattr(items_wear.items_instances, "crack_instance", tracker.crack_instance)

    monkeypatch.setattr(strike.itemsreg, "get_instance", tracker.get_instance)
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", tracker.get_instance)

    monkeypatch.setattr(strike, "item_label", lambda inst, tpl, show_charges=False: inst.get("item_id", ""))
    monkeypatch.setattr(
        monster_actions.item_display,
        "item_label",
        lambda inst, tpl, show_charges=False: inst.get("item_id", ""),
    )

    return tracker


def test_wear_from_event_requires_positive_damage() -> None:
    event = items_wear.build_wear_event(actor="player", source="melee", damage=12)
    assert event["kind"] == items_wear.WEAR_EVENT_KIND
    assert items_wear.wear_from_event(event) == items_wear.WEAR_PER_HIT
    zero_damage_event = items_wear.build_wear_event(actor="player", source="melee", damage=0)
    assert items_wear.wear_from_event(zero_damage_event) == 0
    assert items_wear.wear_from_event(None) == 0


def test_player_hits_crack_weapon_on_twentieth(dummy_instances: DummyInstances) -> None:
    bus = DummyBus()
    tracker = dummy_instances
    tracker.reset()
    catalog = {"test_sword": {}}

    results = []
    for _ in range(20):
        event = items_wear.build_wear_event(actor="player", source="melee", damage=15)
        wear_amount = items_wear.wear_from_event(event)
        results.append(strike._apply_weapon_wear(tracker.iid, wear_amount, catalog, bus))

    assert results[18]["cracked"] is False
    cracked_payload = results[-1]
    assert cracked_payload["cracked"] is True
    assert any("cracks" in message for _, message in bus.messages)
    inst = tracker.get_instance(tracker.iid)
    assert inst is not None
    assert inst.get("item_id") == itemsreg.BROKEN_WEAPON_ID


def test_monster_hits_crack_weapon_on_twentieth(dummy_instances: DummyInstances) -> None:
    bus = DummyBus()
    tracker = dummy_instances
    tracker.reset()
    catalog = {"test_sword": {}}

    monster = {
        "id": "monster-1",
        "name": "Goblin",
        "bag": [{"iid": tracker.iid, "item_id": "test_sword", "origin": "native"}],
        "wielded": tracker.iid,
    }
    ctx = {"feedback_bus": bus}

    results = []
    for _ in range(20):
        event = items_wear.build_wear_event(actor="monster", source="melee", damage=13)
        wear_amount = items_wear.wear_from_event(event)
        results.append(
            monster_actions._apply_weapon_wear(monster, tracker.iid, wear_amount, catalog, bus, ctx)
        )

    assert results[18]["cracked"] is False
    cracked_payload = results[-1]
    assert cracked_payload["cracked"] is True
    assert any("cracks" in message for _, message in bus.messages)
    inst = tracker.get_instance(tracker.iid)
    assert inst is not None
    assert inst.get("item_id") == itemsreg.BROKEN_WEAPON_ID
    assert monster["bag"][0]["item_id"] == itemsreg.BROKEN_WEAPON_ID
