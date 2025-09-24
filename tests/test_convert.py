from typing import Any, Dict

from mutants.commands import convert


def _catalog(meta: Dict[str, Dict[str, Any]]):
    class DummyCatalog:
        def __init__(self, data: Dict[str, Dict[str, Any]]):
            self._data = data

        def get(self, item_id: str):
            return self._data.get(item_id)

    return DummyCatalog(meta)


def test_convert_value_uses_enchant_bonus(monkeypatch):
    levels = {"knife#2": 2, "knife#3": 3}
    monkeypatch.setattr(convert.itemsreg, "get_enchant_level", lambda iid: levels.get(iid, 0))

    catalog = _catalog({"knife": {"convert_ions": 14000}})

    assert convert._convert_value("knife", catalog, "knife#2") == 34200
    assert convert._convert_value("knife", catalog, "knife#3") == 44300


def test_convert_payout_handles_missing_instance(monkeypatch):
    monkeypatch.setattr(convert.itemsreg, "get_enchant_level", lambda _: 0)

    catalog = _catalog({"knife": {"convert_ions": 14000}})

    payout = convert._convert_payout("", "knife", catalog)

    assert payout == 14000


def test_convert_payout_handles_mixed_enchant_levels(monkeypatch):
    levels = {"knife_plain": 0, "knife_plus3": 3}
    monkeypatch.setattr(convert.itemsreg, "get_enchant_level", lambda iid: levels.get(iid, 0))

    catalog = _catalog({"knife": {"convert_ions": 14000}})

    assert convert._convert_payout("knife_plain", "knife", catalog) == 14000
    assert convert._convert_payout("knife_plus3", "knife", catalog) == 44300


def test_choose_inventory_item_skips_non_world(monkeypatch):
    player = {"inventory": ["native#1", "world#2"]}
    catalog = _catalog({"sword": {"name": "Sword"}})

    def fake_get_instance(iid: str) -> dict | None:
        if iid == "native#1":
            return {"iid": iid, "item_id": "sword", "origin": "native"}
        if iid == "world#2":
            return {"iid": iid, "item_id": "sword", "origin": "world"}
        return None

    monkeypatch.setattr(convert.itemsreg, "get_instance", fake_get_instance)

    iid, item_id = convert._choose_inventory_item(player, "swo", catalog)

    assert iid == "world#2"
    assert item_id == "sword"


def test_choose_inventory_item_returns_none_when_no_world(monkeypatch):
    player = {"inventory": ["native#1"]}
    catalog = _catalog({"sword": {"name": "Sword"}})

    monkeypatch.setattr(
        convert.itemsreg,
        "get_instance",
        lambda iid: {"iid": iid, "item_id": "sword", "origin": "native"},
    )

    iid, item_id = convert._choose_inventory_item(player, "swo", catalog)

    assert iid is None and item_id is None
