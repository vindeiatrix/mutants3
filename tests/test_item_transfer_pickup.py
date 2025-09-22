import copy

import pytest

from mutants.services import item_transfer as itx


@pytest.fixture
def pickup_env(monkeypatch):
    ground: list[str] = []
    instances: dict[str, dict[str, object]] = {}
    catalog: dict[str, dict[str, object]] = {}
    stats: dict[str, int] = {"str": 10}

    player = {
        "inventory": [],
        "class": "Fighter",
        "active": {"class": "Fighter", "inventory": [], "pos": [2000, 1, 1]},
        "bags": {"Fighter": []},
    }

    ctx = {
        "player_state": {
            "active_id": "p1",
            "players": [{"id": "p1", "pos": [2000, 1, 1]}],
        }
    }

    def fake_load_player():
        itx._STATE_CACHE = {"stats": copy.deepcopy(stats)}
        return player

    monkeypatch.setattr(itx, "_load_player", fake_load_player)
    monkeypatch.setattr(itx, "_save_player", lambda _player: None)
    monkeypatch.setattr(itx.pstate, "ensure_active_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.pstate, "bind_inventory_to_active_class", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.pstate, "get_stats_for_active", lambda _state: dict(stats))
    monkeypatch.setattr(itx.pstate, "load_state", lambda: {"stats": dict(stats)})
    monkeypatch.setattr(itx.pstate, "save_state", lambda _state: None)

    monkeypatch.setattr(itx.items_probe, "enabled", lambda: False)
    monkeypatch.setattr(itx.items_probe, "probe", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "setup_file_logging", lambda: None)
    monkeypatch.setattr(itx.items_probe, "dump_tile_instances", lambda *args, **kwargs: None)
    monkeypatch.setattr(itx.items_probe, "find_all", lambda *args, **kwargs: None)

    def list_instances_at(_year: int, _x: int, _y: int):
        return [copy.deepcopy(instances[iid]) for iid in ground if iid in instances]

    def clear_position_at(iid: str, _year: int, _x: int, _y: int) -> bool:
        try:
            ground.remove(iid)
            return True
        except ValueError:
            return False

    def clear_position(iid: str) -> bool:
        if iid in ground:
            ground.remove(iid)
            return True
        return False

    def set_position(iid: str, _year: int, _x: int, _y: int) -> None:
        if iid in instances and iid not in ground:
            ground.append(iid)

    monkeypatch.setattr(itx.itemsreg, "list_instances_at", list_instances_at)
    monkeypatch.setattr(itx.itemsreg, "clear_position_at", clear_position_at)
    monkeypatch.setattr(itx.itemsreg, "clear_position", clear_position)
    monkeypatch.setattr(itx.itemsreg, "set_position", set_position)
    monkeypatch.setattr(itx.itemsreg, "save_instances", lambda: None)
    monkeypatch.setattr(itx.itemsreg, "get_instance", lambda iid: copy.deepcopy(instances.get(iid)))

    def add_ground_item(iid: str, item_id: str, *, weight: int, enchant_level: int = 0):
        inst = {
            "iid": iid,
            "instance_id": iid,
            "item_id": item_id,
            "enchant_level": enchant_level,
            "weight": weight,
        }
        instances[iid] = inst
        if iid not in ground:
            ground.append(iid)
        catalog[item_id] = {"name": item_id.replace("_", " ").title(), "weight": weight}

    monkeypatch.setattr(itx.catreg, "load_catalog", lambda: catalog)

    def set_strength(value: int) -> None:
        stats["str"] = value

    return {
        "ctx": ctx,
        "player": player,
        "add_ground_item": add_ground_item,
        "set_strength": set_strength,
        "catalog": catalog,
        "ground": ground,
        "instances": instances,
        "stats": stats,
    }


def test_pickup_strength_gate_blocks_when_too_heavy(pickup_env):
    pickup_env["add_ground_item"]("colossus#ground", "colossus", weight=160, enchant_level=0)
    pickup_env["set_strength"](15)

    result = itx.pick_from_ground(pickup_env["ctx"], "col")

    assert result["ok"] is False
    assert result["reason"] == "insufficient_strength"
    assert result["message"] == "You don't have enough strength to pick that up!"
    assert pickup_env["player"]["inventory"] == []
    assert pickup_env["ground"] == ["colossus#ground"]


def test_pickup_strength_gate_respects_enchant_reduction(pickup_env):
    pickup_env["add_ground_item"]("warhammer#ground", "warhammer", weight=40, enchant_level=2)
    pickup_env["set_strength"](2)

    result = itx.pick_from_ground(pickup_env["ctx"], "war")

    assert result["ok"] is True
    assert pickup_env["player"]["inventory"] == ["warhammer#ground"]
    assert pickup_env["ground"] == []
