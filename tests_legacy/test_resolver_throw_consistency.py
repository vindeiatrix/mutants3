import json
import shutil
from pathlib import Path

from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.registries import items_instances as itemsreg
from mutants.services.item_transfer import throw_to_direction as do_throw
from mutants.util.directions import vec
from mutants import state as state_mod


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
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    iid = itemsreg.create_and_save_instance("skull", 2000, 10, 10)
    itemsreg.clear_position(iid)
    player_entry = pdata["players"][0]
    pdata["inventory"] = [iid]
    player_entry["inventory"] = [iid]
    player_entry["pos"] = [2000, 10, 10]
    active = pdata.get("active")
    if isinstance(active, dict):
        active["inventory"] = [iid]
        active["pos"] = [2000, 10, 10]
    player_active = player_entry.get("active")
    if isinstance(player_active, dict):
        player_active["inventory"] = [iid]
        player_active["pos"] = [2000, 10, 10]
    bags = pdata.get("bags")
    if isinstance(bags, dict):
        for key in list(bags.keys()):
            bags[key] = [iid]
    bags_by_class = pdata.get("bags_by_class")
    if isinstance(bags_by_class, dict):
        for key in list(bags_by_class.keys()):
            bags_by_class[key] = [iid]
    player_bags = player_entry.get("bags")
    if isinstance(player_bags, dict):
        for key in list(player_bags.keys()):
            player_bags[key] = [iid]
    player_bags_by_class = player_entry.get("bags_by_class")
    if isinstance(player_bags_by_class, dict):
        for key in list(player_bags_by_class.keys()):
            player_bags_by_class[key] = [iid]
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
        player_entry = pdata["players"][0]
        pdata["inventory"] = [iid]
        player_entry["inventory"] = [iid]
        active = pdata.get("active")
        if isinstance(active, dict):
            active["inventory"] = [iid]
        player_active = player_entry.get("active")
        if isinstance(player_active, dict):
            player_active["inventory"] = [iid]
        for bag_key in ("bags", "bags_by_class"):
            target = pdata.get(bag_key)
            if isinstance(target, dict):
                for key in list(target.keys()):
                    target[key] = [iid]
        for bag_key in ("bags", "bags_by_class"):
            target = player_entry.get(bag_key)
            if isinstance(target, dict):
                for key in list(target.keys()):
                    target[key] = [iid]
        with pfile.open("w", encoding="utf-8") as f:
            json.dump(pdata, f)
