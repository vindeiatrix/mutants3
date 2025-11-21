from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import sys

sys.path.append("src")

from mutants import state as state_mod
from mutants.commands import debug as debug_cmd
from mutants.commands import get as get_cmd
from mutants.commands import wear as wear_cmd
from mutants.services import item_transfer as itx
from mutants.services import player_state


class DummyBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, channel: str, message: str) -> None:
        self.messages.append((channel, message))


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)
    return tmp_path


class FakeItemsRegistry:
    def __init__(self) -> None:
        self.instances: dict[str, dict] = {}
        self._counter = 0

    def mint_on_ground_with_defaults(
        self, item_id: str, *, year: int, x: int, y: int, origin: str
    ) -> str:
        self._counter += 1
        iid = f"{item_id}-{self._counter}"
        self.instances[iid] = {
            "iid": iid,
            "instance_id": iid,
            "item_id": item_id,
            "year": year,
            "x": x,
            "y": y,
            "origin": origin,
        }
        return iid

    def list_instances_at(self, year: int, x: int, y: int) -> list[dict]:
        return [
            dict(inst)
            for inst in self.instances.values()
            if inst.get("year") == year and inst.get("x") == x and inst.get("y") == y
        ]

    def clear_position_at(self, iid: str, year: int, x: int, y: int) -> bool:
        inst = self.instances.get(iid)
        if inst and inst.get("year") == year and inst.get("x") == x and inst.get("y") == y:
            inst["year"] = None
            inst["x"] = None
            inst["y"] = None
            return True
        return False

    def clear_position(self, iid: str) -> bool:
        inst = self.instances.get(iid)
        if not inst:
            return False
        inst["year"] = None
        inst["x"] = None
        inst["y"] = None
        return True

    def update_instance(
        self, iid: str, *, year: int, x: int, y: int, owner: str | None = None
    ) -> None:
        inst = self.instances.get(iid)
        if not inst:
            return
        inst["year"] = year
        inst["x"] = x
        inst["y"] = y
        if owner is not None:
            inst["owner"] = owner

    def set_position(self, iid: str, year: int, x: int, y: int) -> None:
        inst = self.instances.get(iid)
        if inst:
            inst["year"] = year
            inst["x"] = x
            inst["y"] = y

    def get_instance(self, iid: str) -> dict | None:
        inst = self.instances.get(iid)
        return dict(inst) if inst else None

    def list_at(self, year: int, x: int, y: int):
        for inst in self.list_instances_at(year, x, y):
            yield inst

    def snapshot(self):
        for inst in self.instances.values():
            yield dict(inst)


class FakeCatalog:
    def __init__(self) -> None:
        self._items = {
            "simple_armour": {
                "item_id": "simple_armour",
                "display": "Simple Armour",
                "armour": True,
                "armour_class": 1,
            }
        }

    def get(self, key: str):
        return self._items.get(key)


def _make_initial_state() -> dict:
    return {
        "players": [
            {
                "id": "p1",
                "class": "Thief",
                "pos": [2000, 0, 0],
                "inventory": [],
                "stats": {"str": 10},
            }
        ],
        "active_id": "p1",
        "ions_by_class": {"Thief": 0},
    }


def test_drop_after_remove_leaves_inventory_empty(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player_state.save_state(_make_initial_state())
    canonical = player_state.load_state()

    ctx = {
        "feedback_bus": DummyBus(),
        "player_state": canonical,
        "render_next": False,
        "world_loader": lambda year: SimpleNamespace(year=year),
    }

    fake_items = FakeItemsRegistry()
    catalog = FakeCatalog()

    monkeypatch.setattr(debug_cmd, "itemsreg", fake_items)
    monkeypatch.setattr(debug_cmd, "items_instances", fake_items)
    monkeypatch.setattr(debug_cmd.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(get_cmd, "itemsreg", fake_items)
    monkeypatch.setattr(get_cmd.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(wear_cmd, "itemsreg", fake_items)
    monkeypatch.setattr(wear_cmd.catreg, "load_catalog", lambda: catalog)
    monkeypatch.setattr(wear_cmd, "get_effective_weight", lambda inst, template: 0)
    monkeypatch.setattr(itx, "itemsreg", fake_items)
    monkeypatch.setattr(itx.catreg, "load_catalog", lambda: catalog)
    monkeypatch.setattr(itx, "get_effective_weight", lambda inst, template: 0)
    monkeypatch.setattr(itx.items_probe, "enabled", lambda: False)
    monkeypatch.setattr(itx.items_probe, "probe", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "setup_file_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "dump_tile_instances", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "find_all", lambda *args, **kwargs: None)

    player_state.ensure_player_state(ctx)

    debug_cmd.debug_add_cmd("simple_armour", ctx)
    minted_ids = list(fake_items.instances.keys())
    assert minted_ids
    minted_id = minted_ids[0]

    ctx["player_state"]["players"][0]["inventory"] = [minted_id]
    ctx["player_state"]["players"][0]["bags"] = {"Thief": [minted_id]}
    ctx["player_state"]["bags"] = {"Thief": [minted_id]}
    player_state.save_state(ctx["player_state"])
    ctx["player_state"] = player_state.load_state()

    equipped = player_state.equip_armour(minted_id)
    assert equipped == minted_id
    ctx["player_state"] = player_state.load_state()
    player_state.ensure_player_state(ctx)

    unequipped = player_state.unequip_armour()
    assert unequipped == minted_id
    ctx["player_state"] = player_state.load_state()
    player_state.ensure_player_state(ctx)

    drop_result = itx.drop_to_ground(ctx, "")
    assert drop_result["ok"] is True
    player_state.save_player_state(ctx)

    final_state = player_state.load_state()
    inventory = final_state["players"][0]["inventory"]
    assert inventory == []
    assert fake_items.get_instance(minted_id)["year"] == 2000
    assert fake_items.get_instance(minted_id).get("owner") is None
