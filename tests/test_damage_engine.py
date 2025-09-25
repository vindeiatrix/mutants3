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
    calls: list[tuple[Any, Any, Any]] = []

    def fake_resolve(item: Any, attacker: Any, defender: Any) -> damage_engine.AttackResult:
        calls.append((item, attacker, defender))
        return damage_engine.AttackResult(27, "melee")

    monkeypatch.setattr(damage_engine, "resolve_attack", fake_resolve)

    assert damage_engine.compute_base_damage({}, {}, {}) == 27
    assert calls == [({}, {}, {})]


def test_get_attacker_power_handles_monster_state():
    monster = {"stats": {"str": 47}}
    weapon = {"base_power": 5, "enchant_level": 15}

    # strength bonus = floor(47/10) = 4; enchant bonus = 60
    assert damage_engine.get_attacker_power(weapon, monster) == 5 + 60 + 4


def test_get_total_ac_handles_monster_state():
    armour = {"item_id": "leather", "enchant_level": 3, "derived": {"armour_class": 6}}
    monster = {"stats": {"dex": 28}, "armour_slot": armour}

    # dex bonus = 2, armour = 6 (base 3 + enchant 3)
    assert damage_engine.get_total_ac(monster) == 8


def test_resolve_attack_infers_innate_source():
    attacker = {"stats": {"str": 35}}
    defender = {"derived": {"armour_class": 0}}

    result = damage_engine.resolve_attack({}, attacker, defender)

    assert result.source == "innate"
    assert result.damage == damage_engine.get_attacker_power({}, attacker)


def test_resolve_attack_uses_bolt_power(monkeypatch):
    attacker = _base_state(strength=10)
    defender = {"derived": {"armour_class": 0}}

    monkeypatch.setattr(
        damage_engine.items_catalog,
        "load_catalog",
        lambda: DummyCatalog({"ion_wand": {"base_power_melee": 3, "base_power_bolt": 11}}),
    )

    result = damage_engine.resolve_attack({"item_id": "ion_wand"}, attacker, defender, source="bolt")

    assert result.source == "bolt"
    assert result.damage == 11 + 1  # str bonus is floor(10/10) == 1

