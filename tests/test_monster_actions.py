from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

import pytest

from mutants.services import monster_actions


class _DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_: Any) -> None:
        self.events.append((kind, text))


class _FixedRng:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = list(values)
        if not self._values:
            self._values = [0.0]
        self._idx = 0

    def random(self) -> float:
        value = self._values[min(self._idx, len(self._values) - 1)]
        self._idx += 1
        return value


@pytest.fixture(autouse=True)
def _reset_ai_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monster_actions, "_mark_monsters_dirty", lambda ctx: ctx.setdefault("_dirty", True))


def _force_action(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(monster_actions, "_select_action", lambda m, c, r: name)


def test_attack_uses_innate_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {"id": "ogre#1", "hp": {"current": 10, "max": 10}, "wielded": None}
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    state = {"hp_by_class": {"fighter": {"current": 30, "max": 30}}, "active_id": "player"}
    active = {"hp": {"current": 30, "max": 30}, "stats": {"dex": 10}}

    monkeypatch.setattr(monster_actions.pstate, "get_active_pair", lambda hint=None: (state, active))

    recorded: Dict[str, int] = {}

    def _fake_set_hp(st: Mapping[str, Any], hp: Mapping[str, Any]) -> Mapping[str, Any]:
        recorded.update(hp)  # type: ignore[arg-type]
        return dict(hp)

    monkeypatch.setattr(monster_actions.pstate, "set_hp_for_active", _fake_set_hp)
    monkeypatch.setattr(monster_actions.damage_engine, "compute_base_damage", lambda *args, **kwargs: -5)
    monkeypatch.setattr(monster_actions.items_wear, "wear_from_event", lambda payload: 0)
    monkeypatch.setattr(monster_actions, "_apply_weapon_wear", lambda *args, **kwargs: None)

    _force_action(monkeypatch, "attack")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert recorded["current"] == 24 and recorded["max"] == 30
    assert any("6 damage" in text for _, text in bus.events)


def test_pickup_prefers_stronger_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {"id": "ghoul#1", "hp": {"current": 10, "max": 10}, "pos": [2000, 1, 2], "bag": []}
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    ground_items = [
        {"iid": "weak", "item_id": "club", "enchant_level": 0, "condition": 100},
        {"iid": "strong", "item_id": "blade", "enchant_level": 0, "condition": 100},
    ]

    monkeypatch.setattr(monster_actions.itemsreg, "list_instances_at", lambda *_: ground_items)
    monkeypatch.setattr(monster_actions.itemsreg, "clear_position_at", lambda iid, *args: iid == "strong")
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: next((inst for inst in ground_items if inst["iid"] == iid), None))
    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {"club": {"base_power": 3}, "blade": {"base_power": 9}})

    _force_action(monkeypatch, "pickup")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    bag = monster.get("bag") or []
    assert any(entry.get("iid") == "strong" for entry in bag)
    assert "strong" in monster_actions._picked_up_iids(monster)


def test_convert_only_uses_picked_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "lich#1",
        "hp": {"current": 8, "max": 8},
        "bag": [
            {"iid": "native", "item_id": "dagger", "enchant_level": 0},
            {"iid": "pickup", "item_id": "wand", "enchant_level": 0},
        ],
        "ions": 0,
    }
    monster_actions._add_picked_up(monster, "pickup")

    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {"wand": {"convert_ions": 1200}})
    monkeypatch.setattr(monster_actions.itemsreg, "delete_instance", lambda iid: iid == "pickup")
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": "wand"})

    _force_action(monkeypatch, "convert")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert monster["ions"] == 1200
    assert all(entry.get("iid") != "pickup" for entry in monster["bag"])
    assert "pickup" not in monster_actions._picked_up_iids(monster)
    flash_messages = [text for _, text in bus.events if "blinding white flash" in text]
    assert flash_messages, "convert should emit the blinding white flash line"


def test_remove_broken_armour(monkeypatch: pytest.MonkeyPatch) -> None:
    monster = {
        "id": "goblin#1",
        "hp": {"current": 5, "max": 5},
        "stats": {"dex": 20},
        "derived": {"dex_bonus": 2, "armour_class": 2},
        "armour_slot": {"iid": "broken", "item_id": monster_actions.itemsreg.BROKEN_ARMOUR_ID},
    }
    bus = _DummyBus()
    ctx: Dict[str, Any] = {"feedback_bus": bus}

    monkeypatch.setattr(monster_actions, "_load_catalog", lambda: {})
    monkeypatch.setattr(monster_actions.itemsreg, "get_instance", lambda iid: {"iid": iid, "item_id": monster_actions.itemsreg.BROKEN_ARMOUR_ID})

    _force_action(monkeypatch, "remove_armour")

    monster_actions.execute_random_action(monster, ctx, rng=_FixedRng([0.0]))

    assert monster.get("armour_slot") is None
    derived = monster.get("derived", {})
    assert derived.get("armour_class") == derived.get("dex_bonus")
    assert any("broken armour" in text.lower() for _, text in bus.events)
