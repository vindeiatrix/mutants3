from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from mutants.commands import lock
from mutants.commands._util import items as items_util


class FakeBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, object]]] = []

    def push(self, kind: str, message: str, **meta: object) -> None:
        self.messages.append((kind, message, dict(meta)))


@dataclass
class FakeWorld:
    tiles: dict[tuple[int, int], dict]

    def get_tile(self, x: int, y: int) -> dict:
        return self.tiles.get((x, y), {})


class FakeDyn:
    def __init__(self) -> None:
        self.lock_result = None
        self.set_calls: list[tuple[int, int, int, str, str]] = []

    def get_lock(self, year: int, x: int, y: int, direction: str):
        return self.lock_result

    def set_lock(self, year: int, x: int, y: int, direction: str, key_type: str) -> None:
        self.set_calls.append((year, x, y, direction, key_type))


def configure_inventory(monkeypatch: pytest.MonkeyPatch, items: list[dict]) -> None:
    order = [item["iid"] for item in items]
    inst_map = {item["iid"]: {"item_id": item["item_id"]} for item in items}
    catalog = {
        item["item_id"]: {
            "name": item.get("name"),
            "key": item.get("key", False),
            "key_type": item.get("key_type"),
        }
        for item in items
    }

    monkeypatch.setattr(
        items_util, "inventory_iids_for_active_player", lambda ctx: list(order)
    )
    monkeypatch.setattr(items_util.itemsreg, "get_instance", lambda iid: inst_map.get(iid, {}))
    monkeypatch.setattr(lock.itemsreg, "get_instance", lambda iid: inst_map.get(iid, {}))
    monkeypatch.setattr(items_util.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(lock.items_catalog, "load_catalog", lambda: catalog)


def configure_gate(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeDyn, dict]:
    dyn = FakeDyn()
    monkeypatch.setattr(lock, "dyn", dyn)

    gate_tile = {
        "edges": {
            "W": {"base": lock.BASE_GATE, "gate_state": 1},
        }
    }
    neighbour = {
        "edges": {
            "E": {"base": lock.BASE_GATE, "gate_state": 1},
        }
    }
    world = FakeWorld({(0, 0): gate_tile, (-1, 0): neighbour})

    ctx = {
        "feedback_bus": FakeBus(),
        "player_state": {
            "active_id": 1,
            "players": [{"id": 1, "pos": [1000, 0, 0]}],
        },
        "world_loader": lambda year: world,
    }
    return dyn, ctx


def test_lock_requires_key_argument_shows_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_inventory(monkeypatch, [])
    bus = FakeBus()
    lock.lock_cmd("w", {"feedback_bus": bus})
    assert bus.messages == [
        (
            "SYSTEM/WARN",
            "Usage: lock <direction> <key name>\nExamples: lock west devil-key | loc w d",
            {},
        )
    ]


def test_lock_west_with_exact_key(monkeypatch: pytest.MonkeyPatch) -> None:
    dyn, ctx = configure_gate(monkeypatch)
    configure_inventory(
        monkeypatch,
        [
            {
                "iid": "iid-1",
                "item_id": "devil-key",
                "name": "Devil Key",
                "key": True,
                "key_type": "devil",
            }
        ],
    )

    lock.lock_cmd("west devil-key", ctx)

    assert ctx["feedback_bus"].messages[-1] == (
        "SYSTEM/OK",
        "You lock the gate west.",
        {},
    )
    assert dyn.set_calls == [(1000, 0, 0, "W", "devil")]


def test_lock_alias_uses_prefix_inventory_order(monkeypatch: pytest.MonkeyPatch) -> None:
    dyn, ctx = configure_gate(monkeypatch)
    configure_inventory(
        monkeypatch,
        [
            {
                "iid": "iid-1",
                "item_id": "devil-key",
                "name": "Devil Key",
                "key": True,
                "key_type": "devil",
            },
            {
                "iid": "iid-2",
                "item_id": "dragon-key",
                "name": "Dragon Key",
                "key": True,
                "key_type": "dragon",
            },
        ],
    )

    lock.lock_cmd("w d", ctx)

    assert ctx["feedback_bus"].messages[-1] == (
        "SYSTEM/OK",
        "You lock the gate west.",
        {},
    )
    assert dyn.set_calls == [(1000, 0, 0, "W", "devil")]


def test_lock_warns_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    dyn, ctx = configure_gate(monkeypatch)
    configure_inventory(monkeypatch, [])

    lock.lock_cmd("west d", ctx)

    assert ctx["feedback_bus"].messages[-1] == (
        "SYSTEM/WARN",
        "You're not carrying a d.",
        {},
    )
    assert dyn.set_calls == []
