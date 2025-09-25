import json, shutil
from pathlib import Path

from mutants.services.item_transfer import drop_to_ground
import json
import shutil
from pathlib import Path

import json
import shutil
from pathlib import Path

from mutants.services.item_transfer import drop_to_ground
from mutants.registries import items_instances as itemsreg
from mutants import state as state_mod
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


def _setup_inventory(monkeypatch, tmp_path, item_ids):
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
    player_entry = pdata["players"][0]
    pdata["inventory"] = inv
    player_entry["inventory"] = inv
    active = pdata.get("active")
    if isinstance(active, dict):
        active["inventory"] = inv
    player_active = player_entry.get("active")
    if isinstance(player_active, dict):
        player_active["inventory"] = inv
    bags = pdata.get("bags")
    if isinstance(bags, dict):
        for key in list(bags.keys()):
            bags[key] = inv
    bags_by_class = pdata.get("bags_by_class")
    if isinstance(bags_by_class, dict):
        for key in list(bags_by_class.keys()):
            bags_by_class[key] = inv
    player_bags = player_entry.get("bags")
    if isinstance(player_bags, dict):
        for key in list(player_bags.keys()):
            player_bags[key] = inv
    player_bags_by_class = player_entry.get("bags_by_class")
    if isinstance(player_bags_by_class, dict):
        for key in list(player_bags_by_class.keys()):
            player_bags_by_class[key] = inv
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f)
    ctx = _ctx()
    ctx["player_state"] = {"active_id": pid, "players": [{"id": pid, "pos": [2000, 0, 0]}]}
    return ctx, pfile, inv


def test_drop_prefix_with_identical_name_duplicates(monkeypatch, tmp_path):
    ctx, pfile, inv = _setup_inventory(monkeypatch, tmp_path, ["gold_chunk", "gold_chunk"])
    res = drop_to_ground(ctx, "g")
    assert res["ok"] and res["iid"] == inv[0]
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    inv_after = pdata.get("inventory", [])
    assert inv[0] not in inv_after and inv[1] in inv_after
    ground_iids = [
        inst.get("iid") or inst.get("instance_id")
        for inst in itemsreg.list_instances_at(2000, 0, 0)
    ]
    assert inv[0] in ground_iids and inv[1] not in ground_iids
