from __future__ import annotations

from typing import Any, Dict

from mutants.services import combat_calc


class DummyCatalog:
    def __init__(self, data: Dict[str, Dict[str, Any]]):
        self._data = data

    def get(self, item_id: str):
        return self._data.get(item_id)


def _base_state(dex: int, armour: str | None = None) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "players": [
            {
                "id": "p1",
                "class": "Thief",
            }
        ],
        "active_id": "p1",
        "stats_by_class": {"Thief": {"dex": dex}},
    }
    if armour is not None:
        state["equipment_by_class"] = {"Thief": {"armour": armour}}
    return state


def test_armour_class_without_armour(monkeypatch):
    state = _base_state(dex=35)

    assert combat_calc.armour_class_from_equipped(state) == 0
    assert combat_calc.armour_class_for_active(state) == 3


def test_armour_class_with_equipped_instance(monkeypatch):
    state = _base_state(dex=20, armour="armour#1")

    def fake_get_instance(iid: str):
        if iid == "armour#1":
            return {"iid": iid, "item_id": "chain_mail"}
        return None

    dummy_catalog = DummyCatalog({"chain_mail": {"armour_class": 2}})

    monkeypatch.setattr(combat_calc.itemsreg, "get_instance", fake_get_instance)
    monkeypatch.setattr(combat_calc.items_catalog, "load_catalog", lambda: dummy_catalog)

    assert combat_calc.armour_class_from_equipped(state) == 2
    assert combat_calc.armour_class_for_active(state) == 4


def test_armour_class_from_direct_template(monkeypatch):
    state = _base_state(dex=5, armour="leather_armour")

    dummy_catalog = DummyCatalog({"leather_armour": {"armour_class": 1}})

    monkeypatch.setattr(combat_calc.itemsreg, "get_instance", lambda _: None)
    monkeypatch.setattr(combat_calc.items_catalog, "load_catalog", lambda: dummy_catalog)

    assert combat_calc.armour_class_from_equipped(state) == 1
    assert combat_calc.armour_class_for_active(state) == 1
