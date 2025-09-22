from typing import Any, Dict

from mutants.commands import convert


def _catalog(meta: Dict[str, Dict[str, Any]]):
    class DummyCatalog:
        def __init__(self, data: Dict[str, Dict[str, Any]]):
            self._data = data

        def get(self, item_id: str):
            return self._data.get(item_id)

    return DummyCatalog(meta)


def test_convert_payout_uses_enchant_bonus(monkeypatch):
    monkeypatch.setattr(convert.itemsreg, "get_enchant_level", lambda iid: 2 if iid == "knife#1" else 0)

    catalog = _catalog({"knife": {"convert_ions": 14000}})

    payout = convert._convert_payout("knife#1", "knife", catalog)

    assert payout == 14000 + 2 * 10100


def test_convert_payout_handles_missing_instance(monkeypatch):
    monkeypatch.setattr(convert.itemsreg, "get_enchant_level", lambda _: 0)

    catalog = _catalog({"knife": {"convert_ions": 14000}})

    payout = convert._convert_payout("", "knife", catalog)

    assert payout == 14000
