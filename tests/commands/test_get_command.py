import json, shutil
from pathlib import Path

from src.mutants.commands.get import get_cmd
from src.mutants.registries import items_instances as itemsreg
from src.mutants.ui import item_display as idisp


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
    itemsreg._CACHE = None
    # ensure starting tile has no items
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
    iids = []
    for item_id in ground_items:
        iid = itemsreg.create_and_save_instance(item_id, 2000, 0, 0)
        iids.append(iid)
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pid = pdata["players"][0]["id"]
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
