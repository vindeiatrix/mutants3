import json
import shutil
from pathlib import Path

import pytest

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import debug
from mutants.registries import items_instances as itemsreg, items_catalog
from mutants.services import item_transfer as it
from mutants import state as state_mod


@pytest.fixture
def ctx_with_player(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    shutil.copytree(src_state, dst_state)
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
    player_entry = pdata["players"][0]
    pdata["inventory"] = []
    player_entry["inventory"] = []
    active = pdata.get("active")
    if isinstance(active, dict):
        active["inventory"] = []
    player_active = player_entry.get("active")
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
    player_bags = player_entry.get("bags")
    if isinstance(player_bags, dict):
        for key in list(player_bags.keys()):
            player_bags[key] = []
    player_bags_by_class = player_entry.get("bags_by_class")
    if isinstance(player_bags_by_class, dict):
        for key in list(player_bags_by_class.keys()):
            player_bags_by_class[key] = []
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f, indent=2)
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
    ctx = context.build_context()
    return ctx


@pytest.fixture
def run_cmd(ctx_with_player):
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx_with_player["feedback_bus"])
    debug.register(dispatch, ctx_with_player)

    def _run(cmd: str):
        token, *rest = cmd.split(" ", 1)
        arg = rest[0] if rest else ""
        dispatch.call(token, arg)

    return _run


@pytest.fixture
def list_inv_names():
    def _list():
        p = it._load_player()
        inv = p.get("inventory") or []
        cat = items_catalog.load_catalog()
        names = []
        for iid in inv:
            inst = itemsreg.get_instance(iid)
            if not inst:
                continue
            item_id = inst.get("item_id")
            meta = cat.get(item_id) if cat else None
            if isinstance(meta, dict) and meta.get("name"):
                names.append(meta["name"])
            else:
                names.append(item_id)
        return names

    return _list


@pytest.fixture
def inv_count_by_item_id():
    def _count(item_id: str) -> int:
        p = it._load_player()
        inv = p.get("inventory") or []
        cnt = 0
        for iid in inv:
            inst = itemsreg.get_instance(iid)
            if inst and inst.get("item_id") == item_id:
                cnt += 1
        return cnt

    return _count


def test_debug_add_gate_keys(ctx_with_player, run_cmd, list_inv_names):
    run_cmd("debug add gate_key_a")
    run_cmd("debug add gate_key_b")
    names = list_inv_names()
    assert "Gate-Key A" in names
    assert "Gate-Key B" in names


def test_debug_add_invalid_id_fails_cleanly(ctx_with_player, run_cmd, list_inv_names):
    before = set(list_inv_names())
    run_cmd("debug add not_a_real_id")
    after = set(list_inv_names())
    assert before == after


def test_debug_add_quantity(ctx_with_player, run_cmd, inv_count_by_item_id):
    run_cmd("debug add gate_key_a 3")
    assert inv_count_by_item_id("gate_key_a") == 3
