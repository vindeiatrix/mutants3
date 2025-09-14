import json, shutil
from pathlib import Path

from src.mutants.commands.drop import drop_cmd
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


def _setup_inventory(monkeypatch, tmp_path, item_ids):
    src_state = Path(__file__).resolve().parents[1] / "state"
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
    inv = []
    for item_id in item_ids:
        iid = itemsreg.create_and_save_instance(item_id, 2000, 0, 0)
        itemsreg.clear_position(iid)
        inv.append(iid)
    pfile = Path("state/playerlivestate.json")
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pid = pdata["players"][0]["id"]
    pdata["inventory"] = inv
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)
    ctx = _ctx()
    ctx["player_state"] = {"active_id": pid, "players": [{"id": pid, "pos": [2000, 0, 0]}]}
    return ctx, pfile, inv


def test_drop_prefix_true_ambiguity_prompts(monkeypatch, tmp_path):
    ctx, pfile, inv = _setup_inventory(monkeypatch, tmp_path, ["ion_pack", "ion_booster"])
    drop_cmd("ion", ctx)
    kinds = [k for (k, _m) in ctx["feedback_bus"].events]
    assert any(k.endswith("/WARN") for k in kinds)
    text = " ".join(m for (_k, m) in ctx["feedback_bus"].events)
    assert "Be more specific" in text and "Ion-Pack" in text and "Ion-Booster" in text
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert set(pdata.get("inventory", [])) == set(inv)
