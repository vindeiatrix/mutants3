import json
import shutil
from pathlib import Path
import pytest

from mutants.services.item_transfer import throw_to_direction as do_throw
from mutants.registries import items_instances as itemsreg
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
    iid = itemsreg.create_and_save_instance("skull", 2000, 0, 0)
    itemsreg.clear_position(iid)
    pdata["inventory"] = [iid]
    pdata["players"][0]["inventory"] = [iid]
    pdata["players"][0]["pos"] = [2000, 10, 10]
    active = pdata.get("active")
    if isinstance(active, dict):
        active["inventory"] = [iid]
        active["pos"] = [2000, 10, 10]
    bags = pdata.get("bags")
    if isinstance(bags, dict):
        for key in list(bags.keys()):
            bags[key] = [iid]
    bags_by_class = pdata.get("bags_by_class")
    if isinstance(bags_by_class, dict):
        for key in list(bags_by_class.keys()):
            bags_by_class[key] = [iid]
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)
    ctx = _ctx()
    ctx["player_state"] = {
        "active_id": pdata["players"][0]["id"],
        "players": [{"id": pdata["players"][0]["id"], "pos": [2000, 10, 10]}],
    }
    return ctx, iid


@pytest.mark.parametrize(
    "direction,dx,dy",
    [
        ("north", 0, 1),
        ("south", 0, -1),
        ("east", 1, 0),
        ("west", -1, 0),
    ],
)
def test_throw_lands_correct_tile(monkeypatch, tmp_path, direction, dx, dy):
    ctx, iid = _setup(monkeypatch, tmp_path)
    res = do_throw(ctx, direction, None)
    assert res["ok"]
    inst = itemsreg.get_instance(iid)
    pos = inst.get("pos", {})
    year, x, y = pos.get("year"), pos.get("x"), pos.get("y")
    assert (year, x, y) == (2000, 10 + dx, 10 + dy)
