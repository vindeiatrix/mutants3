import json, shutil
from pathlib import Path

from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg
from mutants.services.item_transfer import throw_to_direction as do_throw
from mutants.util.directions import vec


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


def _setup(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    itemsreg._CACHE = None
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    iid = itemsreg.create_and_save_instance("skull", 2000, 10, 10)
    itemsreg.clear_position(iid)
    pdata["inventory"] = [iid]
    pdata["players"][0]["pos"] = [2000, 10, 10]
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)
    ctx = _ctx()
    ctx["player_state"] = {
        "active_id": pdata["players"][0]["id"],
        "players": [{"id": pdata["players"][0]["id"], "pos": [2000, 10, 10]}],
    }
    return ctx, iid


def test_resolver_and_throw_consistent(monkeypatch, tmp_path):
    ctx, iid = _setup(monkeypatch, tmp_path)
    year, x, y = 2000, 10, 10
    world = ctx["world_loader"](year)
    for direction in ["north", "south", "east", "west"]:
        dx, dy = vec(direction)
        dec = ER.resolve(world, dyn, year, x, y, direction[:1].upper(), actor={})
        assert dec.passable
        res = do_throw(ctx, direction, None)
        assert res["ok"]
        inst = itemsreg.get_instance(iid)
        pos = inst.get("pos", {})
        assert (pos.get("year"), pos.get("x"), pos.get("y")) == (year, x + dx, y + dy)
        # reset item back to inventory for next direction
        itemsreg.clear_position(iid)
        pfile = Path("state/playerlivestate.json")
        with pfile.open("r", encoding="utf-8") as f:
            pdata = json.load(f)
        pdata["inventory"].append(iid)
        with pfile.open("w", encoding="utf-8") as f:
            json.dump(pdata, f)
