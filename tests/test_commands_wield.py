import copy

import pytest

from mutants.commands import wield
from mutants.registries import items_catalog, items_instances as itemsreg
from mutants.services import player_state as pstate


class Bus:
    def __init__(self) -> None:
        self.msgs: list[tuple[str, str]] = []

    def push(self, kind: str, msg: str) -> None:
        self.msgs.append((kind, msg))


def _make_state(
    bag_items: list[str],
    stats: dict[str, int],
    *,
    wielded: str | None = None,
    extra_classes: list[tuple[str, list[str], dict[str, int]]] | None = None,
) -> dict[str, object]:
    equipment_entry: dict[str, dict[str, str | None]] = {"Thief": {"armour": None}}
    wield_map: dict[str, str | None] = {"Thief": wielded}
    bags: dict[str, list[str]] = {"Thief": list(bag_items)}
    stats_by_class: dict[str, dict[str, int]] = {"Thief": dict(stats)}

    players: list[dict[str, object]] = [
        {
            "id": "p1",
            "class": "Thief",
            "pos": [2000, 1, 1],
            "inventory": list(bag_items),
            "bags": {"Thief": list(bag_items)},
            "equipment_by_class": copy.deepcopy(equipment_entry),
            "wielded_by_class": {"Thief": wielded},
            "armour": {"wearing": None},
            "wielded": wielded,
            "stats": dict(stats),
        }
    ]

    if extra_classes:
        for idx, (cls_name, extra_bag, extra_stats) in enumerate(extra_classes, start=2):
            equipment_entry[cls_name] = {"armour": None}
            wield_map[cls_name] = None
            bags[cls_name] = list(extra_bag)
            stats_by_class[cls_name] = dict(extra_stats)
            players.append(
                {
                    "id": f"p{idx}",
                    "class": cls_name,
                    "pos": [2000, idx, idx],
                    "inventory": list(extra_bag),
                    "bags": {cls_name: list(extra_bag)},
                    "equipment_by_class": {cls_name: {"armour": None}},
                    "wielded_by_class": {cls_name: None},
                    "armour": {"wearing": None},
                    "wielded": None,
                    "stats": dict(extra_stats),
                }
            )

    return {
        "players": players,
        "active_id": "p1",
        "inventory": list(bag_items),
        "bags": bags,
        "equipment_by_class": copy.deepcopy(equipment_entry),
        "wielded_by_class": copy.deepcopy(wield_map),
        "active": {
            "class": "Thief",
            "pos": [2000, 1, 1],
            "inventory": list(bag_items),
            "equipment_by_class": copy.deepcopy(equipment_entry),
            "wielded_by_class": copy.deepcopy(wield_map),
            "armour": {"wearing": None},
            "wielded": wielded,
            "stats": dict(stats),
        },
        "armour": {"wearing": None},
        "wielded": wielded,
        "stats_by_class": stats_by_class,
    }


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

    def fake_cache() -> list[dict[str, object]]:
        return instances_list

    monkeypatch.setattr(itemsreg, "_cache", fake_cache)
    monkeypatch.setattr(itemsreg, "_save_instances_raw", lambda _: None)
    monkeypatch.setattr(itemsreg, "save_instances", lambda: None)

    def setup(
        *,
        bag_items: list[str],
        stats: dict[str, int],
        catalog: dict[str, dict[str, object]],
        instances: dict[str, dict[str, object]],
        wielded: str | None = None,
        extra_classes: list[tuple[str, list[str], dict[str, int]]] | None = None,
    ) -> None:
        state_store.clear()
        state_store.update(_make_state(bag_items, stats, wielded=wielded, extra_classes=extra_classes))
        catalog_data.clear()
        catalog_data.update(copy.deepcopy(catalog))
        instances_list.clear()
        for iid, meta in instances.items():
            payload = dict(meta)
            item_id = payload.pop("item_id", None)
            enchant_level = payload.pop("enchant_level", 0)
            inst = {
                "iid": iid,
                "instance_id": iid,
                "item_id": item_id,
                "enchanted": "no",
                "enchant_level": enchant_level,
                "condition": 100,
            }
            inst.update(payload)
            instances_list.append(inst)
        from mutants.services import item_transfer as itx

        itx._STATE_CACHE = None

    return {"setup": setup, "state": state_store, "catalog": catalog_data, "instances": instances_list}


def test_wield_sets_active_weapon(command_env):
    stats = {"str": 12, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["long_sword#bag"],
        stats=stats,
        catalog={"long_sword": {"name": "Long Sword", "weight": 10}},
        instances={"long_sword#bag": {"item_id": "long_sword"}},
    )

    state_before = pstate.load_state()
    ctx, bus = _ctx(state_before)
    result = wield.wield_cmd("long", ctx)

    assert result["ok"] is True
    assert any("You wield the Long Sword." in msg for _, msg in bus.msgs)

    state_after = pstate.load_state()
    assert pstate.get_wielded_weapon_id(state_after) == "long_sword#bag"
    assert "long_sword#bag" in state_after["bags"]["Thief"]  # type: ignore[index]
    assert state_after["wielded_by_class"]["Thief"] == "long_sword#bag"  # type: ignore[index]


def test_wield_strength_gate_failure(command_env):
    stats = {"str": 3, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["warhammer#bag"],
        stats=stats,
        catalog={"warhammer": {"name": "Warhammer", "weight": 25}},
        instances={"warhammer#bag": {"item_id": "warhammer"}},
    )

    state_before = pstate.load_state()
    ctx, bus = _ctx(state_before)
    result = wield.wield_cmd("war", ctx)

    assert result["ok"] is False
    assert any("You don't have the strength to wield that!" in msg for _, msg in bus.msgs)
    assert pstate.get_wielded_weapon_id(pstate.load_state()) is None


def test_wield_allows_enchanted_weapon_with_reduced_weight(command_env):
    stats = {"str": 4, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["warhammer#bag"],
        stats=stats,
        catalog={"warhammer": {"name": "Warhammer", "weight": 40}},
        instances={"warhammer#bag": {"item_id": "warhammer", "enchant_level": 2}},
    )

    state_before = pstate.load_state()
    ctx, bus = _ctx(state_before)
    result = wield.wield_cmd("war", ctx)

    assert result["ok"] is True
    assert any("You wield the Warhammer." in msg for _, msg in bus.msgs)
    assert pstate.get_wielded_weapon_id(pstate.load_state()) == "warhammer#bag"


def test_wield_uses_prefix_resolution(command_env):
    stats = {"str": 6, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    command_env["setup"](
        bag_items=["short_sword#bag", "long_sword#bag"],
        stats=stats,
        catalog={
            "short_sword": {"name": "Short Sword", "weight": 5},
            "long_sword": {"name": "Long Sword", "weight": 10},
        },
        instances={
            "short_sword#bag": {"item_id": "short_sword"},
            "long_sword#bag": {"item_id": "long_sword"},
        },
    )

    state_before = pstate.load_state()
    ctx, bus = _ctx(state_before)
    wield.wield_cmd("lon", ctx)

    state_after = pstate.load_state()
    assert pstate.get_wielded_weapon_id(state_after) == "long_sword#bag"
    assert any("You wield the Long Sword." in msg for _, msg in bus.msgs)


def test_wield_persists_per_class(command_env):
    stats = {"str": 8, "dex": 10, "int": 0, "wis": 0, "con": 0, "cha": 0}
    extra = [("Wizard", ["wand#bag"], {"str": 5, "dex": 9, "int": 12, "wis": 11, "con": 8, "cha": 7})]
    command_env["setup"](
        bag_items=["long_sword#bag"],
        stats=stats,
        catalog={
            "long_sword": {"name": "Long Sword", "weight": 10},
            "wand": {"name": "Wizard's Wand", "weight": 2},
        },
        instances={
            "long_sword#bag": {"item_id": "long_sword"},
            "wand#bag": {"item_id": "wand"},
        },
        extra_classes=extra,
    )

    ctx, bus = _ctx(pstate.load_state())
    wield.wield_cmd("long", ctx)
    assert any("You wield the Long Sword." in msg for _, msg in bus.msgs)

    state_after = pstate.load_state()
    wield_map = state_after["wielded_by_class"]  # type: ignore[index]
    assert wield_map["Thief"] == "long_sword#bag"  # type: ignore[index]
    assert wield_map["Wizard"] is None  # type: ignore[index]
