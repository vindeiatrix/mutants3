from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from mutants.commands import convert, drop, inv, look, point
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate


class Bus:
    def __init__(self) -> None:
        self.msgs: List[tuple[str, str]] = []

    def push(self, kind: str, msg: str) -> None:
        self.msgs.append((kind, msg))


def _make_state(bag_iid: str, equipped_iid: str) -> Dict[str, Any]:
    equipment_entry = {"Thief": {"armour": equipped_iid}}
    return {
        "players": [
            {
                "id": "p1",
                "class": "Thief",
                "pos": [2000, 1, 1],
                "inventory": [bag_iid, equipped_iid],
                "bags": {"Thief": [bag_iid, equipped_iid]},
                "equipment_by_class": copy.deepcopy(equipment_entry),
                "armour": {"wearing": equipped_iid},
            }
        ],
        "active_id": "p1",
        "inventory": [bag_iid, equipped_iid],
        "bags": {"Thief": [bag_iid, equipped_iid]},
        "equipment_by_class": copy.deepcopy(equipment_entry),
        "active": {
            "class": "Thief",
            "pos": [2000, 1, 1],
            "inventory": [bag_iid, equipped_iid],
            "equipment_by_class": copy.deepcopy(equipment_entry),
            "armour": {"wearing": equipped_iid},
        },
        "armour": {"wearing": equipped_iid},
    }


@pytest.fixture
def equipment_env(monkeypatch):
    bag_iid = "padded_armour#bag"
    equipped_iid = "chain_mail#equipped"

    instances: List[Dict[str, Any]] = [
        {
            "iid": bag_iid,
            "instance_id": bag_iid,
            "item_id": "padded_armour",
            "enchanted": "no",
            "enchant_level": 0,
            "condition": 100,
        },
        {
            "iid": equipped_iid,
            "instance_id": equipped_iid,
            "item_id": "chain_mail",
            "enchanted": "no",
            "enchant_level": 0,
            "condition": 100,
        },
    ]

    catalog = {
        "padded_armour": {
            "name": "Padded Armour",
            "armour": True,
            "convert_ions": 5,
        },
        "chain_mail": {
            "name": "Chain Mail",
            "armour": True,
            "convert_ions": 10,
        },
    }

    state_store: Dict[str, Any] = _make_state(bag_iid, equipped_iid)

    def fake_load_state() -> Dict[str, Any]:
        return copy.deepcopy(state_store)

    def fake_save_state(new_state: Dict[str, Any]) -> None:
        state_store.clear()
        state_store.update(copy.deepcopy(new_state))

    monkeypatch.setattr(pstate, "load_state", fake_load_state)
    monkeypatch.setattr(pstate, "save_state", fake_save_state)

    monkeypatch.setattr(items_catalog, "load_catalog", lambda: catalog)

    def fake_cache() -> List[Dict[str, Any]]:
        return instances

    monkeypatch.setattr(itemsreg, "_cache", fake_cache)
    monkeypatch.setattr(itemsreg, "_save_instances_raw", lambda _: None)
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)

    delete_calls: List[str] = []
    orig_delete = itemsreg.delete_instance

    def record_delete(iid: str) -> int:
        delete_calls.append(iid)
        return orig_delete(iid)

    monkeypatch.setattr(itemsreg, "delete_instance", record_delete)

    set_pos_calls: List[str] = []
    orig_set_position = itemsreg.set_position

    def record_set_position(iid: str, year: int, x: int, y: int) -> None:
        set_pos_calls.append(iid)
        return orig_set_position(iid, year, x, y)

    monkeypatch.setattr(itemsreg, "set_position", record_set_position)

    from mutants.services import item_transfer as itx

    itx._STATE_CACHE = None

    env = {
        "bag_iid": bag_iid,
        "equipped_iid": equipped_iid,
        "instances": instances,
        "state_store": state_store,
        "delete_calls": delete_calls,
        "set_pos_calls": set_pos_calls,
    }

    return env


def _ctx_with_bus(state: Dict[str, Any]) -> tuple[Dict[str, Any], Bus]:
    bus = Bus()
    ctx = {
        "feedback_bus": bus,
        "bus": bus,
        "player_state": copy.deepcopy(state),
        "world_loader": lambda _year: {},
        "headers": {},
    }
    return ctx, bus


def _assert_not_visible(bus: Bus, needle: str) -> None:
    assert all(needle not in msg for _, msg in bus.msgs)


def test_equipped_armour_hidden_from_core_commands(equipment_env):
    state_store = equipment_env["state_store"]
    equipped_iid = equipment_env["equipped_iid"]

    ctx, bus = _ctx_with_bus(state_store)
    look.look_cmd("chain", ctx)
    _assert_not_visible(bus, "Chain Mail")

    ctx, bus = _ctx_with_bus(state_store)
    inv.inv_cmd("", ctx)
    _assert_not_visible(bus, "Chain Mail")

    ctx, bus = _ctx_with_bus(state_store)
    convert.convert_cmd("chain", ctx)
    assert any("You're not carrying a chain." in msg for _, msg in bus.msgs)
    assert equipment_env["delete_calls"] == []

    ctx, bus = _ctx_with_bus(state_store)
    drop.drop_cmd("chain", ctx)
    assert any("You can't drop what you're wearing." in msg for _, msg in bus.msgs)
    assert equipment_env["set_pos_calls"] == []

    ctx, bus = _ctx_with_bus(state_store)
    point.point_cmd("north chain", ctx)
    assert any("You're not carrying a chain." in msg for _, msg in bus.msgs)

    snapshot = itemsreg.snapshot_instances()
    broken_ids = {itemsreg.BROKEN_ARMOUR_ID, itemsreg.BROKEN_WEAPON_ID}
    for inst in snapshot:
        assert "enchant_level" in inst
        item_id = inst.get("item_id")
        enchanted = str(inst.get("enchanted", "")).lower() == "yes"
        if item_id not in broken_ids and not enchanted:
            assert "condition" in inst

    def _check_equipment_block(payload: Dict[str, Any]) -> None:
        equipment = payload.get("equipment_by_class")
        assert isinstance(equipment, dict)
        entry = equipment.get("Thief")
        assert isinstance(entry, dict)
        assert "armour" in entry

    _check_equipment_block(state_store)
    _check_equipment_block(state_store["players"][0])
    _check_equipment_block(state_store["active"])

    for payload in (state_store, state_store["players"][0], state_store["active"]):
        equipment = payload.get("equipment_by_class")
        if isinstance(equipment, dict):
            equipment.pop("Thief", None)
        payload.pop("armour", None)

    ctx, bus = _ctx_with_bus(state_store)
    drop.drop_cmd("chain", ctx)
    assert any("Chain" in msg for _, msg in bus.msgs)
    assert any("drop" in msg.lower() for _, msg in bus.msgs)
    assert equipment_env["set_pos_calls"] == [equipped_iid]
