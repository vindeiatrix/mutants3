from __future__ import annotations

import types

from mutants.commands import inv as inv_cmd


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, chan: str, msg: str) -> None:
        self.events.append((chan, msg))


def _mk_ctx() -> tuple[DummyBus, dict[str, object]]:
    bus = DummyBus()
    ctx = {"feedback_bus": bus}
    return bus, ctx


def test_inv_empty_inventory_uses_legacy_message(monkeypatch):
    bus, ctx = _mk_ctx()

    monkeypatch.setattr(
        inv_cmd.pstate,
        "get_active_pair",
        lambda: ({"players": []}, {"inventory": []}),
    )
    monkeypatch.setattr(inv_cmd.itemsreg, "get_instance", lambda _iid: None)
    monkeypatch.setattr(inv_cmd.items_catalog, "load_catalog", lambda: types.SimpleNamespace(get=lambda *_: {}))

    inv_cmd.inv_cmd("", ctx)

    assert bus.events == [
        ("SYSTEM/OK", "You are carrying the following items:  (Total Weight: 0 LB's)"),
        ("SYSTEM/OK", "Nothing."),
    ]


def test_inv_reports_total_weight_when_known(monkeypatch):
    bus, ctx = _mk_ctx()

    inv = ["sword#1"]
    inst = {"iid": "sword#1", "instance_id": "sword#1", "item_id": "sword", "weight": 2}

    monkeypatch.setattr(
        inv_cmd.pstate,
        "get_active_pair",
        lambda: ({"players": []}, {"inventory": inv}),
    )
    monkeypatch.setattr(inv_cmd.itemsreg, "get_instance", lambda iid: inst if iid == "sword#1" else None)

    class DummyCatalog:
        def get(self, item_id: str):
            if item_id == "sword":
                return {"item_id": "sword", "weight": 2}
            return {}

    monkeypatch.setattr(inv_cmd.items_catalog, "load_catalog", lambda: DummyCatalog())

    inv_cmd.inv_cmd("", ctx)

    assert bus.events[0] == (
        "SYSTEM/OK",
        "You are carrying the following items:  (Total Weight: 2 LB's)",
    )
    # Display line uses NBSP for the article binding. Ensure item is listed.
    assert any("Sword" in msg for _, msg in bus.events[1:])
