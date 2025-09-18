import json, shutil
import json, shutil
from pathlib import Path
import pytest

from src.mutants.commands.throw import throw_cmd
from src.mutants.registries import items_instances as itemsreg
from src.mutants.services import item_transfer as itx


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


def _setup(monkeypatch, tmp_path, item_ids):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    itemsreg._CACHE = None
    # clear any pre-existing ground items to avoid interference
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    for inst in itemsreg.list_instances_at(2000, 0, 1):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
    inv = []
    for item_id in item_ids:
        iid = itemsreg.create_and_save_instance(item_id, 2000, 0, 0)
        itemsreg.clear_position(iid)
        inv.append(iid)
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pdata["inventory"] = inv
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)
    ctx = _ctx()
    ctx["player_state"] = {
        "active_id": pdata["players"][0]["id"],
        "players": [
            {"id": pdata["players"][0]["id"], "pos": [2000, 0, 0]}
        ],
    }
    return ctx, pfile, inv


@pytest.mark.skip(reason="Name lookup handled elsewhere")
def test_throw_moves_item_to_adjacent_tile(monkeypatch, tmp_path):
    ctx, pfile, inv = _setup(monkeypatch, tmp_path, ["nuclear_decay"])
    iid = inv[0]
    throw_cmd("north nuclear", ctx)
    inst = itemsreg.get_instance(iid)
    assert inst.get("pos", {}).get("x") == 0
    assert inst.get("pos", {}).get("y") == 1
    with pfile.open("r", encoding="utf-8") as f:
        pdata_after = json.load(f)
    assert pdata_after.get("inventory") == []


def test_thrown_item_can_be_picked_up(monkeypatch, tmp_path):
    ctx, pfile, inv = _setup(monkeypatch, tmp_path, ["nuclear_decay"])
    iid = inv[0]
    throw_cmd("north nuclear", ctx)
    assert "nuclear_decay" in itemsreg.list_ids_at(2000, 0, 1)
    ctx["player_state"]["players"][0]["pos"] = [2000, 0, 1]
    dec = itx.pick_from_ground(ctx, "nuclear")
    assert dec.get("ok")
    with pfile.open("r", encoding="utf-8") as f:
        pdata_after = json.load(f)
    assert iid in pdata_after.get("inventory")


def test_throw_invalid_item_warns(monkeypatch, tmp_path):
    ctx, _pfile, _inv = _setup(monkeypatch, tmp_path, ["nuclear_decay"])
    throw_cmd("north junk", ctx)
    events = ctx["feedback_bus"].events
    assert any("not carrying" in m for _, m in events)


def test_throw_abbreviation(monkeypatch, tmp_path):
    ctx, _pfile, inv = _setup(monkeypatch, tmp_path, ["nuclear_decay"])
    iid = inv[0]
    throw_cmd("north n", ctx)
    inst = itemsreg.get_instance(iid)
    assert inst.get("pos", {}).get("y") == 1


@pytest.mark.skip(reason="Name lookup handled elsewhere")
def test_throw_direction_prefix(monkeypatch, tmp_path):
    ctx, pfile, inv = _setup(monkeypatch, tmp_path, ["nuclear_decay"])
    iid = inv[0]
    throw_cmd("we nuclear", ctx)
    inst = itemsreg.get_instance(iid)
    assert inst.get("pos", {}).get("x") == -1

@pytest.mark.skip(reason="ctx fixture not available")
def test_throw_open_exit_goes_to_destination(ctx):
    item = ctx.items_instances.create_and_save_instance("nuclear-rock")
    ctx.player["inventory"] = [item["iid"]]

    # assume north is open
    ctx.commands.throw_cmd("nuclear-rock n", ctx)

    assert item["iid"] not in ctx.player["inventory"]
    dest_ground = ctx.items_ground.load((ctx.year, ctx.pos[0], ctx.pos[1] + 1))
    assert any(i["iid"] == item["iid"] for i in dest_ground)

@pytest.mark.skip(reason="ctx fixture not available")
def test_throw_into_non_exit_drops_current_tile(ctx):
    item = ctx.items_instances.create_and_save_instance("nuclear-rock")
    ctx.player["inventory"] = [item["iid"]]

    # no west exit at this tile
    ctx.commands.throw_cmd("nuclear-rock w", ctx)

    assert item["iid"] not in ctx.player["inventory"]
    ground = ctx.items_ground.load((ctx.year, *ctx.pos))
    assert any(i["iid"] == item["iid"] for i in ground)

@pytest.mark.skip(reason="ctx fixture not available")
def test_throw_closed_gate_drops_current_tile(ctx):
    item = ctx.items_instances.create_and_save_instance("nuclear-rock")
    ctx.player["inventory"] = [item["iid"]]

    # set north edge to gate, closed
    ctx.world.set_gate(ctx.pos, "N", open=False)

    ctx.commands.throw_cmd("nuclear-rock n", ctx)

    assert item["iid"] not in ctx.player["inventory"]
    ground = ctx.items_ground.load((ctx.year, *ctx.pos))
    assert any(i["iid"] == item["iid"] for i in ground)

@pytest.mark.skip(reason="ctx fixture not available")
def test_throw_boundary_drops_current_tile(ctx):
    item = ctx.items_instances.create_and_save_instance("nuclear-rock")
    ctx.player["inventory"] = [item["iid"]]

    # place player at north map boundary
    ctx.pos = (0, ctx.world.max_y)

    ctx.commands.throw_cmd("nuclear-rock n", ctx)

    assert item["iid"] not in ctx.player["inventory"]
    ground = ctx.items_ground.load((ctx.year, *ctx.pos))
    assert any(i["iid"] == item["iid"] for i in ground)




