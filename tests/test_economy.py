from __future__ import annotations

from typing import Any, Dict

from mutants.services import economy


class DummyCatalog:
    def __init__(self, data: Dict[str, Dict[str, Any]]):
        self._data = data

    def get(self, item_id: str | None):
        if item_id is None:
            return None
        return self._data.get(item_id)


def _patch_common(monkeypatch, template: Dict[str, Any], *, condition: int = 100, enchant_level: int = 0):
    inst = {"iid": "item#1", "item_id": "widget"}

    monkeypatch.setattr(economy.itemsreg, "get_instance", lambda iid: inst if iid == "item#1" else None)
    monkeypatch.setattr(economy.itemsreg, "get_enchant_level", lambda iid: enchant_level)
    monkeypatch.setattr(economy.itemsreg, "get_condition", lambda iid: condition)

    dummy_catalog = DummyCatalog({"widget": template})
    monkeypatch.setattr(economy.items_catalog, "load_catalog", lambda: dummy_catalog)


def test_sell_price_scales_with_condition(monkeypatch):
    template = {"riblet_value": 1000}
    _patch_common(monkeypatch, template, condition=100, enchant_level=0)
    assert economy.sell_price_for("item#1") == 1000

    _patch_common(monkeypatch, template, condition=40, enchant_level=0)
    assert economy.sell_price_for("item#1") == 400


def test_sell_price_ignores_condition_for_enchanted(monkeypatch):
    template = {"riblet_value": 800}
    _patch_common(monkeypatch, template, condition=25, enchant_level=2)

    expected = 800 * (100 + 2 * 25) // 100
    assert economy.sell_price_for("item#1") == expected


def test_repair_cost_grows_with_condition_points(monkeypatch):
    template = {"riblet_value": 500}
    _patch_common(monkeypatch, template, condition=40, enchant_level=0)

    # repairing 20 points should cost 20 * 5% of base -> 500
    assert economy.repair_cost_for("item#1", 60) == 500

    # repairing all the way to 100 costs more than a smaller repair
    assert economy.repair_cost_for("item#1", 100) > economy.repair_cost_for("item#1", 60)


def test_repair_cost_zero_when_no_repair_needed(monkeypatch):
    template = {"riblet_value": 750}
    _patch_common(monkeypatch, template, condition=90, enchant_level=0)

    assert economy.repair_cost_for("item#1", 80) == 0
