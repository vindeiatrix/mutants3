import copy

import pytest

from mutants.commands import remove, wear
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import combat_calc, item_transfer as itx, player_state as pstate


class Bus:
    def __init__(self) -> None:
        self.msgs: list[tuple[str, str]] = []

    def push(self, kind: str, msg: str) -> None:
        self.msgs.append((kind, msg))


def _make_state(
    bag_items: list[str],
    equipped: str | None,
    stats: dict[str, int],
) -> dict[str, object]:
    equipment_entry = {"Thief": {"armour": equipped}}
    base = {
        "players": [
            {
                "id": "p1",
                "class": "Thief",
                "pos": [2000, 1, 1],
                "inventory": list(bag_items),
                "bags": {"Thief": list(bag_items)},
                "equipment_by_class": copy.deepcopy(equipment_entry),
                "armour": {"wearing": equipped},
                "stats": dict(stats),
            }
        ],
        "active_id": "p1",
        "inventory": list(bag_items),
        "bags": {"Thief": list(bag_items)},
        "equipment_by_class": copy.deepcopy(equipment_entry),
        "active": {
            "class": "Thief",
            "pos": [2000, 1, 1],
            "inventory": list(bag_items),
            "equipment_by_class": copy.deepcopy(equipment_entry),
            "armour": {"wearing": equipped},
            "stats": dict(stats),
        },
        "armour": {"wearing": equipped},
        "stats_by_class": {"Thief": dict(stats)},
    }
    return base


def _ctx(state: dict[str, object]) -> tuple[dict[str, object], Bus]:
    bus = Bus()
    ctx = {
        "feedback_bus": bus,
        "bus": bus,
        "player_state": copy.deepcopy(state),
        "world_loader": lambda _year: {},
        "headers": {},
    }
    return ctx, bus


@pytest.fixture
def command_env(monkeypatch):
    state_store: dict[str, object] = {}
    catalog_data: dict[str, dict[str, object]] = {}
    instances_list: list[dict[str, object]] = []

    def fake_load_state() -> dict[str, object]:
        return copy.deepcopy(state_store)

    def fake_save_state(new_state: dict[str, object]) -> None:
        state_store.clear()
        state_store.update(copy.deepcopy(new_state))

    monkeypatch.setattr(pstate, "load_state", fake_load_state)
    monkeypatch.setattr(pstate, "save_state", fake_save_state)

    monkeypatch.setattr(items_catalog, "load_catalog", lambda: catalog_data)

    def fake_load() -> list[dict[str, object]]:
        return instances_list

    def fake_save(raw: list[dict[str, object]]) -> None:
        instances_list[:] = list(raw)
        itemsreg.invalidate_cache()

    monkeypatch.setattr(itemsreg, "_load_instances_raw", fake_load)
    monkeypatch.setattr(itemsreg, "_save_instances_raw", fake_save)
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)
    itemsreg.invalidate_cache()

    def setup(
        *,
        bag_items: list[str],
        equipped: str | None,
        stats: dict[str, int],
        catalog: dict[str, dict[str, object]],
        instances: dict[str, dict[str, object] | str],
    ) -> None:
        state_store.clear()
        state_store.update(_make_state(bag_items, equipped, stats))
        catalog_data.clear()
        catalog_data.update(copy.deepcopy(catalog))
        instances_list.clear()
        for iid, meta in instances.items():
            if isinstance(meta, str):
                item_id = meta
                extra: dict[str, object] = {}
            else:
                item_id = meta.get("item_id")
                extra = {k: v for k, v in meta.items() if k != "item_id"}
            inst = {
                "iid": iid,
                "instance_id": iid,
                "item_id": item_id,
                "enchanted": "no",
                "enchant_level": extra.pop("enchant_level", 0),
                "condition": 100,
            }
            inst.update(extra)
            instances_list.append(inst)
        itemsreg.invalidate_cache()
        itx._STATE_CACHE = None

    return {"setup": setup, "state": state_store, "catalog": catalog_data, "instances": instances_list}


def test_wear_equips_armour_and_updates_ac(command_env):
    stats = {"str": 12, "dex": 20, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["padded_armour#bag"],
        equipped=None,
        stats=stats,
        catalog={
            "padded_armour": {"name": "Padded Armour", "armour": True, "armour_class": 2, "weight": 5},
        },
        instances={"padded_armour#bag": "padded_armour"},
    )

    state_before = pstate.load_state()
    assert combat_calc.armour_class_for_active(state_before) == 2

    ctx, bus = _ctx(state_before)
    wear.wear_cmd("padd", ctx)

    assert any("You've just put on the Padded Armour." in msg for _, msg in bus.msgs)

    state_after = pstate.load_state()
    assert combat_calc.armour_class_for_active(state_after) == 4
    assert pstate.get_equipped_armour_id(state_after) == "padded_armour#bag"


def test_wear_rejects_when_too_heavy(command_env):
    stats = {"str": 3, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["chain_mail#bag"],
        equipped=None,
        stats=stats,
        catalog={"chain_mail": {"name": "Chain Mail", "armour": True, "weight": 40}},
        instances={"chain_mail#bag": "chain_mail"},
    )

    state = pstate.load_state()
    ctx, bus = _ctx(state)
    wear.wear_cmd("chain", ctx)

    assert any("You don't have the strength to put that on!" in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) is None


def test_monster_wear_bypasses_strength_gate(command_env):
    stats = {"str": 1, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["chain_mail#bag"],
        equipped=None,
        stats=stats,
        catalog={"chain_mail": {"name": "Chain Mail", "armour": True, "weight": 40}},
        instances={"chain_mail#bag": "chain_mail"},
    )

    state = pstate.load_state()
    ctx, bus = _ctx(state)
    ctx["actor_kind"] = "monster"

    result = wear.wear_cmd("chain", ctx)

    assert result["ok"] is True
    assert not any("You don't have the strength to put that on!" in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) == "chain_mail#bag"


def test_wear_requires_strength_for_150_lb_armour(command_env):
    stats = {"str": 14, "dex": 8, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["massive_armour#bag"],
        equipped=None,
        stats=stats,
        catalog={
            "massive_armour": {
                "name": "Massive Armour",
                "armour": True,
                "armour_class": 7,
                "weight": 150,
            }
        },
        instances={"massive_armour#bag": "massive_armour"},
    )

    ctx, bus = _ctx(pstate.load_state())
    result = wear.wear_cmd("massive", ctx)

    assert result == {"ok": False, "reason": "insufficient_strength"}
    assert any("You don't have the strength to put that on!" in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) is None


def test_wear_allows_149_lb_armour_with_strength_fourteen(command_env):
    stats = {"str": 14, "dex": 8, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["heavy_brigandine#bag"],
        equipped=None,
        stats=stats,
        catalog={
            "heavy_brigandine": {
                "name": "Heavy Brigandine",
                "armour": True,
                "armour_class": 6,
                "weight": 149,
            }
        },
        instances={"heavy_brigandine#bag": "heavy_brigandine"},
    )

    ctx, bus = _ctx(pstate.load_state())
    result = wear.wear_cmd("heavy", ctx)

    assert result["ok"] is True
    assert any("You've just put on the Heavy Brigandine." in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) == "heavy_brigandine#bag"


def test_wear_allows_enchanted_armour_with_reduced_weight(command_env):
    stats = {"str": 2, "dex": 12, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["plate_mail#bag"],
        equipped=None,
        stats=stats,
        catalog={
            "plate_mail": {
                "name": "Plate Mail",
                "armour": True,
                "weight": 40,
                "armour_class": 6,
            }
        },
        instances={
            "plate_mail#bag": {"item_id": "plate_mail", "enchant_level": 2},
        },
    )

    ctx, bus = _ctx(pstate.load_state())
    result = wear.wear_cmd("plate", ctx)

    assert result["ok"] is True
    assert any("You've just put on the Plate Mail." in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) == "plate_mail#bag"


def test_remove_fails_when_bag_full(command_env):
    bag_items = [f"junk#{idx}" for idx in range(9)] + ["padded_armour#bag"]
    stats = {"str": 12, "dex": 15, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=bag_items,
        equipped="chain_mail#equipped",
        stats=stats,
        catalog={
            "chain_mail": {"name": "Chain Mail", "armour": True, "weight": 4},
            "padded_armour": {"name": "Padded Armour", "armour": True, "weight": 3},
        },
        instances={
            "chain_mail#equipped": "chain_mail",
            "padded_armour#bag": "padded_armour",
            **{item: "scrap" for item in bag_items if item.startswith("junk#")},
        },
    )

    state = pstate.load_state()
    ctx, bus = _ctx(state)
    remove.remove_cmd("", ctx)

    assert any("You're to encumbered to do that!" in msg for _, msg in bus.msgs)
    assert pstate.get_equipped_armour_id(pstate.load_state()) == "chain_mail#equipped"


def test_wear_swaps_when_already_equipped(command_env):
    bag_items = [f"junk#{idx}" for idx in range(9)] + ["padded_armour#bag"]
    stats = {"str": 12, "dex": 18, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=bag_items,
        equipped="chain_mail#equipped",
        stats=stats,
        catalog={
            "chain_mail": {"name": "Chain Mail", "armour": True, "weight": 4, "armour_class": 2},
            "padded_armour": {"name": "Padded Armour", "armour": True, "weight": 3, "armour_class": 1},
        },
        instances={
            "chain_mail#equipped": "chain_mail",
            "padded_armour#bag": "padded_armour",
            **{item: "scrap" for item in bag_items if item.startswith("junk#")},
        },
    )

    state = pstate.load_state()
    ctx, bus = _ctx(state)
    wear.wear_cmd("padded", ctx)

    messages = [msg for _, msg in bus.msgs]
    assert "You've removed the Chain Mail." in messages
    assert "You've just put on the Padded Armour." in messages

    state_after = pstate.load_state()
    bag_after = state_after["bags"]["Thief"]  # type: ignore[index]
    assert "chain_mail#equipped" in bag_after
    assert "padded_armour#bag" not in bag_after
    assert len(bag_after) == 10


def test_remove_places_armour_in_bag(command_env):
    stats = {"str": 9, "dex": 12, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["junk#1"],
        equipped="chain_mail#equipped",
        stats=stats,
        catalog={"chain_mail": {"name": "Chain Mail", "armour": True, "weight": 4}},
        instances={"chain_mail#equipped": "chain_mail", "junk#1": "scrap"},
    )

    state = pstate.load_state()
    ctx, bus = _ctx(state)
    remove.remove_cmd("", ctx)

    assert any("You remove the Chain Mail." in msg for _, msg in bus.msgs)
    state_after = pstate.load_state()
    assert pstate.get_equipped_armour_id(state_after) is None
    assert "chain_mail#equipped" in state_after["bags"]["Thief"]  # type: ignore[index]
