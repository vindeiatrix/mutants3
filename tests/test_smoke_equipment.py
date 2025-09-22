from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from mutants.commands import convert, drop, inv, look, point, wear
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_calc, player_state as pstate

from tests.test_commands_wear_remove import _make_state as _make_command_state


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


def test_smoke_strength_gate_and_broken_armour(equipment_env):
    heavy_iid = "heavy_plate#bag"
    broken_iid = "broken_armour#bag"
    chain_iid = equipment_env["equipped_iid"]

    junk_ids = [f"junk#{idx}" for idx in range(8)]
    bag_items = [heavy_iid, broken_iid, *junk_ids]
    base_stats = {"str": 14, "dex": 0, "int": 0, "wis": 0, "con": 0, "cha": 0}

    state_store = equipment_env["state_store"]
    state_store.clear()
    state_store.update(_make_command_state(bag_items, chain_iid, base_stats))

    catalog = items_catalog.load_catalog()
    catalog.clear()
    catalog.update(
        {
            "heavy_plate": {
                "name": "Heavy Plate",
                "armour": True,
                "armour_class": 8,
                "weight": 150,
            },
            "chain_mail": {
                "name": "Chain Mail",
                "armour": True,
                "armour_class": 5,
                "weight": 45,
            },
            itemsreg.BROKEN_ARMOUR_ID: {
                "name": "Broken Armour",
                "armour": True,
                "armour_class": 0,
                "weight": 0,
            },
            "scrap": {"name": "Scrap"},
        }
    )

    instances = equipment_env["instances"]
    instances.clear()

    def _add_instance(iid: str, item_id: str, **extra: object) -> None:
        inst = {
            "iid": iid,
            "instance_id": iid,
            "item_id": item_id,
            "enchanted": extra.pop("enchanted", "no"),
            "enchant_level": extra.pop("enchant_level", 0),
            "condition": extra.pop("condition", 100),
        }
        inst.update(extra)
        instances.append(inst)

    _add_instance(heavy_iid, "heavy_plate", weight=150)
    _add_instance(chain_iid, "chain_mail", weight=45)
    _add_instance(broken_iid, itemsreg.BROKEN_ARMOUR_ID, condition=0, weight=0)
    for iid in junk_ids:
        _add_instance(iid, "scrap", weight=5)

    from mutants.services import item_transfer as itx

    itx._STATE_CACHE = None

    ctx, bus = _ctx_with_bus(pstate.load_state())
    fail_result = wear.wear_cmd("heavy", ctx)

    assert fail_result == {"ok": False, "reason": "insufficient_strength"}
    assert any(
        "You don't have the strength to put that on!" in msg for _, msg in bus.msgs
    )
    assert pstate.get_equipped_armour_id(pstate.load_state()) == chain_iid

    state_store["players"][0]["stats"]["str"] = 15
    state_store["active"]["stats"]["str"] = 15
    state_store["stats_by_class"]["Thief"]["str"] = 15

    pstate.save_state(copy.deepcopy(state_store))

    loaded_after_boost = pstate.load_state()
    assert heavy_iid in loaded_after_boost["bags"]["Thief"]  # type: ignore[index]

    ctx, bus = _ctx_with_bus(loaded_after_boost)
    success = wear.wear_cmd("heavy", ctx)

    assert success == {
        "ok": True,
        "iid": heavy_iid,
        "item_id": "heavy_plate",
        "swapped": chain_iid,
    }
    messages = [msg for _, msg in bus.msgs]
    assert "You've removed the Chain Mail." in messages
    assert "You've just put on the Heavy Plate." in messages

    equipped_state = pstate.load_state()
    bag_after = equipped_state["bags"]["Thief"]  # type: ignore[index]
    assert chain_iid in bag_after
    assert heavy_iid not in bag_after
    assert len(bag_after) == len(bag_items)
    assert pstate.get_equipped_armour_id(equipped_state) == heavy_iid

    state_store["players"][0]["stats"]["str"] = 0
    state_store["active"]["stats"]["str"] = 0
    state_store["stats_by_class"]["Thief"]["str"] = 0

    pstate.save_state(copy.deepcopy(state_store))

    ctx, bus = _ctx_with_bus(pstate.load_state())
    broken_result = wear.wear_cmd("broken", ctx)

    assert broken_result == {
        "ok": True,
        "iid": broken_iid,
        "item_id": itemsreg.BROKEN_ARMOUR_ID,
        "swapped": heavy_iid,
    }
    assert any("You've removed the Heavy Plate." in msg for _, msg in bus.msgs)
    assert any("You've just put on the Broken Armour." in msg for _, msg in bus.msgs)

    final_state = pstate.load_state()
    final_bag = final_state["bags"]["Thief"]  # type: ignore[index]
    assert heavy_iid in final_bag
    assert len(final_bag) == len(bag_items)
    assert pstate.get_equipped_armour_id(final_state) == broken_iid
    assert combat_calc.armour_class_for_active(final_state) == 0


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
