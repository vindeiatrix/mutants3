from __future__ import annotations

from mutants.commands import fix as fix_cmd


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


def test_fix_rejects_zero_charge_item(monkeypatch):
    bus = DummyBus()
    ctx = {"feedback_bus": bus}

    monkeypatch.setattr(fix_cmd, "find_inventory_item_by_prefix", lambda *_: "i.blaster")
    monkeypatch.setattr(
        fix_cmd.itemsreg,
        "get_instance",
        lambda iid: {"iid": iid, "item_id": "blaster", "charges": 0},
    )
    monkeypatch.setattr(
        fix_cmd.itemsreg, "recharge_full", lambda *_: (_ for _ in ()).throw(AssertionError("should not recharge"))
    )
    monkeypatch.setattr(
        fix_cmd.items_catalog,
        "load_catalog",
        lambda: {"blaster": {"item_id": "blaster", "charges_max": 5, "name": "Blaster"}},
    )

    fix_cmd.fix_cmd("blaster", ctx)

    assert bus.messages == [("SYSTEM/WARN", "I can't fix that!")]

