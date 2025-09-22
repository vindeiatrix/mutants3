from __future__ import annotations

from typing import Any, Dict

from mutants.services import damage_engine


class DummyCatalog:
    def __init__(self, payload: Dict[str, Dict[str, Any]]):
        self._payload = payload

    def get(self, item_id: str):
        return self._payload.get(item_id)


def _base_state(strength: int) -> Dict[str, Any]:
    return {
        "players": [{"id": "p1", "class": "Thief"}],
        "active_id": "p1",
        "stats_by_class": {"Thief": {"str": strength}},
    }


def test_get_total_ac_delegates_to_combat_calc(monkeypatch):
    calls: list[Any] = []

    def fake_armour_class(state):
        calls.append(state)
        return 17.2

    monkeypatch.setattr(
        damage_engine.combat_calc,
        "armour_class_for_active",
        fake_armour_class,
    )

    state = {"active_id": "p1"}
    assert damage_engine.get_total_ac(state) == 17
    assert calls == [state]


def test_get_attacker_power_with_inline_payload():
    state = _base_state(strength=25)
    item = {"base_power": 30, "enchant_level": 3}
    assert damage_engine.get_attacker_power(item, state) == 30 + 12 + 2


def test_get_attacker_power_resolves_instance_and_template(monkeypatch):
    state = _base_state(strength=55)

    def fake_get_instance(iid: str):
        if iid == "weapon#1":
            return {"iid": iid, "item_id": "ion_decay"}
        return None

    monkeypatch.setattr(damage_engine.itemsreg, "get_instance", fake_get_instance)
    monkeypatch.setattr(
        damage_engine.itemsreg,
        "get_enchant_level",
        lambda iid: 5 if iid == "weapon#1" else 0,
    )
    monkeypatch.setattr(
        damage_engine.items_catalog,
        "load_catalog",
        lambda: DummyCatalog({"ion_decay": {"base_power": 7}}),
    )

    assert damage_engine.get_attacker_power("weapon#1", state) == 7 + 20 + 5


def test_compute_base_damage_uses_helpers(monkeypatch):
    monkeypatch.setattr(damage_engine, "get_attacker_power", lambda *args, **kwargs: 42)
    monkeypatch.setattr(damage_engine, "get_total_ac", lambda state: 15)

    assert damage_engine.compute_base_damage({}, {}, {}) == 27

