from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mutants import state as state_mod
from mutants.commands import debug as debug_cmd
from mutants.commands import get as get_cmd
from mutants.commands import move as move_cmd
from mutants.commands import travel as travel_cmd
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


class _PassableDecision(SimpleNamespace):
    pass


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
        "ions_by_class": {"Thief": 15000},
    }


def test_travel_and_move_share_canonical_state(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    player_state.save_state(_make_initial_state())

    canonical = player_state.load_state()
    ctx = {
        "feedback_bus": DummyBus(),
        "player_state": canonical,
        "render_next": False,
        "world_loader": lambda year: SimpleNamespace(year=year),
        "world_years": [2000, 2100, 2200, 2300],
    }

    monkeypatch.setattr(
        move_cmd.ER,
        "resolve",
        lambda world, dyn_mod, year, x, y, dir_code, actor=None: _PassableDecision(
            passable=True,
            descriptor="open",
            reason=None,
            reason_chain=[],
            cur_raw={},
            nbr_raw={},
        ),
    )

    travel_cmd.travel_cmd("2300", ctx)

    after_travel = player_state.load_state()
    assert after_travel["players"][0]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["players"][0]["pos"] == [2300, 0, 0]
    assert ctx["player_state"]["active"]["pos"] == [2300, 0, 0]
    assert ctx["_active_view"]["pos"] == [2300, 0, 0]

    move_cmd.move("E", ctx)
    move_cmd.move("N", ctx)

    final_state = player_state.load_state()
    expected = [2300, 1, 1]
    assert final_state["players"][0]["pos"] == expected
    assert final_state["pos"] == expected
    assert ctx["player_state"]["players"][0]["pos"] == expected
    assert ctx["player_state"]["active"]["pos"] == expected
    assert ctx["_active_view"]["pos"] == expected
    assert ctx["render_next"] is True


class FakeItemsRegistry:
    def __init__(self) -> None:
        self.instances: dict[str, dict] = {}
        self._counter = 0

    def mint_on_ground_with_defaults(self, item_id: str, *, year: int, x: int, y: int, origin: str) -> str:
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
        return [dict(inst) for inst in self.instances.values() if inst.get("year") == year and inst.get("x") == x and inst.get("y") == y]

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
            "nuclear_de": {"item_id": "nuclear_de", "display": "Nuclear-Decay"}
        }
        self._by_id = dict(self._items)
        self._items_list = list(self._items.values())

    def get(self, key: str):
        return self._items.get(key)


def test_debug_add_and_pick_updates_canonical_inventory(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player_state.save_state(_make_initial_state())
    canonical = player_state.load_state()

    ctx = {
        "feedback_bus": DummyBus(),
        "player_state": canonical,
        "render_next": False,
    }

    fake_items = FakeItemsRegistry()
    catalog = FakeCatalog()

    monkeypatch.setattr(debug_cmd, "itemsreg", fake_items)
    monkeypatch.setattr(debug_cmd, "items_instances", fake_items)
    monkeypatch.setattr(debug_cmd.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(get_cmd, "itemsreg", fake_items)
    monkeypatch.setattr(get_cmd.items_catalog, "load_catalog", lambda: catalog)
    monkeypatch.setattr(itx, "itemsreg", fake_items)
    monkeypatch.setattr(itx.catreg, "load_catalog", lambda: catalog)
    monkeypatch.setattr(itx, "get_effective_weight", lambda inst, template: 0)
    monkeypatch.setattr(itx.items_probe, "enabled", lambda: False)
    monkeypatch.setattr(itx.items_probe, "probe", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "setup_file_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "dump_tile_instances", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "find_all", lambda *args, **kwargs: None)

    player_state.ensure_player_state(ctx)

    debug_cmd.debug_add_cmd("nuclear-de", ctx)
    minted_ids = list(fake_items.instances.keys())
    assert minted_ids
    minted_id = minted_ids[0]

    get_cmd.get_cmd("nuclear-de", ctx)
    player_state.save_player_state(ctx)

    refreshed = player_state.load_state()
    inventory = refreshed["players"][0]["inventory"]
    assert minted_id in inventory
    assert ctx["player_state"]["players"][0]["inventory"] == inventory
    assert ctx["player_state"]["active"]["inventory"] == inventory

