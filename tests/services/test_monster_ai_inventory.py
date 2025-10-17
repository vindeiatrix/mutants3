from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

import sys

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants.services.monster_ai import inventory  # noqa: E402


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str, **_kwargs: object) -> None:
        self.messages.append((channel, message))


class DummyMonstersState:
    def __init__(self) -> None:
        self.dirty_calls = 0

    def mark_dirty(self) -> None:
        self.dirty_calls += 1


class DummyRNG:
    def __init__(self, rolls: list[int]) -> None:
        self.rolls = rolls

    def randrange(self, stop: int) -> int:
        if not self.rolls:
            raise RuntimeError("no rolls left")
        value = self.rolls.pop(0)
        if stop <= 0:
            return 0
        return value % stop


@pytest.fixture(autouse=True)
def patch_turnlog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory.turnlog, "emit", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def patch_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory.items_catalog, "load_catalog", lambda: {"broken_weapon": {}, "broken_armour": {}})
    monkeypatch.setattr(
        inventory.item_display,
        "item_label",
        lambda inst, tpl, show_charges=False: str(inst.get("item_id", "item")),
    )


@pytest.fixture(autouse=True)
def patch_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory.monsters_state, "_refresh_monster_derived", lambda monster: None)


@pytest.fixture
def ctx() -> Dict[str, Any]:
    return {"feedback_bus": DummyBus(), "monsters": DummyMonstersState()}


def test_schedule_weapon_drop_sets_pending_state(ctx: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "m1",
        "name": "Goblin",
        "pos": (2000, 1, 1),
        "bag": [{"iid": "w1", "item_id": "broken_weapon", "enchant_level": 0}],
        "wielded": "w1",
    }

    monkeypatch.setattr(inventory.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "broken_weapon"})
    monkeypatch.setattr(inventory.combat_loot, "drop_existing_iids", lambda iids, pos: iids)

    inventory.schedule_weapon_drop(monster, "w1")

    state = monster.get("_ai_state", {})
    assert state.get("pending_drop") == {"kind": "weapon", "iid": "w1", "attempts": 0}


def test_weapon_drop_respects_chance(ctx: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "m2",
        "pos": (2000, 2, 2),
        "bag": [{"iid": "w2", "item_id": "broken_weapon", "enchant_level": 0}],
        "wielded": "w2",
        "_ai_state": {"pending_drop": {"kind": "weapon", "iid": "w2", "attempts": 0}},
    }

    monkeypatch.setattr(inventory.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "broken_weapon"})
    monkeypatch.setattr(inventory.combat_loot, "drop_existing_iids", lambda iids, pos: iids)

    rng = DummyRNG([95])
    result = inventory.process_pending_drops(monster, ctx, rng)

    assert result["weapon"] is False
    assert result["attempted_weapon"] is True
    state = monster.get("_ai_state", {})
    pending = state.get("pending_drop")
    assert isinstance(pending, dict)
    assert pending.get("attempts") == 1
    assert monster["bag"]  # still holding weapon


def test_weapon_drop_succeeds_and_clears_state(ctx: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "m3",
        "pos": (2000, 3, 3),
        "bag": [{"iid": "w3", "item_id": "broken_weapon", "enchant_level": 0}],
        "wielded": "w3",
        "_ai_state": {"pending_drop": {"kind": "weapon", "iid": "w3", "attempts": 1}},
    }

    drop_calls: list[list[str]] = []

    def fake_drop(iids: list[str], pos: tuple[int, int, int]) -> list[str]:
        drop_calls.append(iids)
        return iids

    monkeypatch.setattr(inventory.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "broken_weapon"})
    monkeypatch.setattr(inventory.combat_loot, "drop_existing_iids", fake_drop)

    rng = DummyRNG([10])
    result = inventory.process_pending_drops(monster, ctx, rng)

    assert result["weapon"] is True
    assert monster.get("wielded") is None
    assert monster.get("bag") == []
    assert monster.get("_ai_state", {}).get("pending_drop") is None
    assert drop_calls == [["w3"]]


def test_armour_drop_is_immediate(ctx: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "m4",
        "pos": (2000, 4, 4),
        "armour_slot": {"iid": "a1", "item_id": "broken_armour"},
        "bag": [],
    }

    drop_calls: list[list[str]] = []

    def fake_drop(iids: list[str], pos: tuple[int, int, int]) -> list[str]:
        drop_calls.append(iids)
        return iids

    monkeypatch.setattr(inventory.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "broken_armour"})
    monkeypatch.setattr(inventory.combat_loot, "drop_existing_iids", fake_drop)

    rng = DummyRNG([0])
    result = inventory.process_pending_drops(monster, ctx, rng)

    assert result["armour"] is True
    assert monster.get("armour_slot") is None
    assert drop_calls == [["a1"]]
