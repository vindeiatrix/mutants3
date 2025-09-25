import json
import shutil
from pathlib import Path

from mutants.commands.get import get_cmd
from mutants.registries import items_instances as itemsreg
from mutants import state as state_mod
from mutants.ui import item_display as idisp


class DummyWorld:
    def get_tile(self, year, x, y):
        return {
            "edges": {
                "N": {"base": 0},
                "S": {"base": 0},
                "E": {"base": 0},
                "W": {"base": 0},
            }
        }


class FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, text, **_):
        self.events.append((kind, text))


def _ctx():
    world = DummyWorld()
    return {"feedback_bus": FakeBus(), "world_loader": lambda year: world}


def _copy_state(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def _setup(monkeypatch, tmp_path, ground_items):
    src_state = Path(__file__).resolve().parents[2] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GAME_STATE_ROOT", str(dst_state))
    monkeypatch.setattr(state_mod, "STATE_ROOT", dst_state)
    monkeypatch.setattr(
        itemsreg,
        "DEFAULT_INSTANCES_PATH",
        state_mod.state_path("items", "instances.json"),
    )
    monkeypatch.setattr(
        itemsreg,
        "FALLBACK_INSTANCES_PATH",
        state_mod.state_path("instances.json"),
    )
    monkeypatch.setattr(
        itemsreg,
        "CATALOG_PATH",
        state_mod.state_path("items", "catalog.json"),
    )
    itemsreg.invalidate_cache()
    # ensure starting tile has no items
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
    for item_id in ground_items:
        itemsreg.create_and_save_instance(item_id, 2000, 0, 0)
    itemsreg.invalidate_cache()
    iids = [
        str(inst.get("iid") or inst.get("instance_id"))
        for inst in itemsreg.list_instances_at(2000, 0, 0)
    ]
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pid = pdata["players"][0]["id"]
    pdata["inventory"] = []
    pdata["players"][0]["inventory"] = []
    active = pdata.get("active")
    if isinstance(active, dict):
        active["inventory"] = []
    player_active = pdata["players"][0].get("active")
    if isinstance(player_active, dict):
        player_active["inventory"] = []
    bags = pdata.get("bags")
    if isinstance(bags, dict):
        for key in list(bags.keys()):
            bags[key] = []
    bags_by_class = pdata.get("bags_by_class")
    if isinstance(bags_by_class, dict):
        for key in list(bags_by_class.keys()):
            bags_by_class[key] = []
    player_bags = pdata["players"][0].get("bags")
    if isinstance(player_bags, dict):
        for key in list(player_bags.keys()):
            player_bags[key] = []
    player_bags_by_class = pdata["players"][0].get("bags_by_class")
    if isinstance(player_bags_by_class, dict):
        for key in list(player_bags_by_class.keys()):
            player_bags_by_class[key] = []
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f, indent=2)
    ctx = _ctx()
    ctx["player_state"] = {
        "active_id": pid,
        "players": [{"id": pid, "pos": [2000, 0, 0]}],
    }
    return ctx, pfile, iids


import pytest


@pytest.mark.parametrize("token", ["i", "ion"])
def test_get_prefix_picks_first_match(monkeypatch, tmp_path, token):
    ctx, pfile, iids = _setup(monkeypatch, tmp_path, ["ion_pack", "ion_booster"])
    get_cmd(token, ctx)
    assert ctx["feedback_bus"].events == [
        ("LOOT/PICKUP", "You pick up the Ion-Pack."),
    ]
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert iids[0] in pdata.get("inventory", [])
    ground_ids = itemsreg.list_ids_at(2000, 0, 0)
    assert "ion_pack" not in ground_ids
    assert "ion_booster" in ground_ids


def test_get_longer_prefix_picks_second(monkeypatch, tmp_path):
    ctx, pfile, iids = _setup(monkeypatch, tmp_path, ["ion_pack", "ion_booster"])
    get_cmd("ion-b", ctx)
    assert ctx["feedback_bus"].events == [
        ("LOOT/PICKUP", "You pick up the Ion-Booster."),
    ]
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert iids[1] in pdata.get("inventory", [])
    ground_ids = itemsreg.list_ids_at(2000, 0, 0)
    assert "ion_booster" not in ground_ids
    assert "ion_pack" in ground_ids


@pytest.mark.skip(reason="Unicode dash naming no longer validated")
def test_get_unicode_dash(monkeypatch, tmp_path):
    ctx, pfile, iids = _setup(monkeypatch, tmp_path, ["nuclear_decay"])

    get_cmd("nuclear-decay", ctx)
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert iids[0] in pdata.get("inventory", [])


def test_get_not_found(monkeypatch, tmp_path):
    ctx, pfile, _iids = _setup(monkeypatch, tmp_path, ["ion_pack"])
    get_cmd("xyz", ctx)
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/WARN", "There isn't a xyz here."),
    ]
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert not pdata.get("inventory")
    ground_ids = itemsreg.list_ids_at(2000, 0, 0)
    assert "ion_pack" in ground_ids
