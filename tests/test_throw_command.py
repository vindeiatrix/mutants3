import json, shutil
from pathlib import Path

from src.mutants.commands.throw import throw_cmd
from src.mutants.registries import items_instances as itemsreg


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


def test_throw_moves_item_to_adjacent_tile(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)
    monkeypatch.chdir(tmp_path)

    iid = itemsreg.create_and_save_instance("nuclear_decay", 2000, 0, 0)
    itemsreg.clear_position(iid)

    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pdata["inventory"] = [iid]
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)

    ctx = _ctx()
    ctx["player_state"] = {
        "active_id": pdata["players"][0]["id"],
        "players": [
            {"id": pdata["players"][0]["id"], "pos": [2000, 0, 0]}
        ],
    }

    throw_cmd("north nuclear", ctx)

    bus_events = ctx["feedback_bus"].events
    assert bus_events == [
        ("COMBAT/THROW", "You throw the Nuclear-Decay north."),
    ]

    inst = itemsreg.get_instance(iid)
    assert inst.get("pos", {}).get("x") == 0
    assert inst.get("pos", {}).get("y") == -1

    with pfile.open("r", encoding="utf-8") as f:
        pdata_after = json.load(f)
    assert pdata_after.get("inventory") == []
