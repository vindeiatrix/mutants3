import shutil
from pathlib import Path

import json
import shutil
from pathlib import Path

import pytest

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import debug, inv, look, point, fix
from mutants.registries import items_instances as itemsreg
from mutants.commands._helpers import inventory_iids_for_active_player
from mutants import state as state_mod


@pytest.fixture
def ctx(monkeypatch, tmp_path):
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
    # Clear positions to simplify
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
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
    return context.build_context()


@pytest.fixture
def run(ctx):
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    debug.register(dispatch, ctx)
    inv.register(dispatch, ctx)
    look.register(dispatch, ctx)
    point.register(dispatch, ctx)
    fix.register(dispatch, ctx)

    def _run(cmd: str):
        token, *rest = cmd.split(" ", 1)
        arg = rest[0] if rest else ""
        dispatch.call(token, arg)

    return _run


def _first_inventory_iid(ctx) -> str:
    return inventory_iids_for_active_player(ctx)[0]


def test_ranged_item_flow(ctx, run):
    run("debug add lightning-rod")
    ctx["feedback_bus"].drain()
    run("inv")
    events = ctx["feedback_bus"].drain()
    assert any("Lightning" in ev["text"] for ev in events)
    assert not any("(25)" in ev["text"] for ev in events)

    run("look lightning")
    events = ctx["feedback_bus"].drain()
    assert any("Charges: 25" in ev["text"] for ev in events)

    run("point west lightning")
    events = ctx["feedback_bus"].drain()
    assert any("fire the Lightning Rod to the West" in ev["text"] for ev in events)
    iid = _first_inventory_iid(ctx)
    assert itemsreg.get_instance(iid).get("charges") == 24

    for _ in range(24):
        itemsreg.spend_charge(iid)
    run("point west lightning")
    events = ctx["feedback_bus"].drain()
    assert any("no charge left" in ev["text"] for ev in events)

    run("fix lightning")
    events = ctx["feedback_bus"].drain()
    assert any("restore the Lightning Rod to full charge" in ev["text"] for ev in events)
    run("inv")
    events = ctx["feedback_bus"].drain()
    assert any("Lightning" in ev["text"] for ev in events)
    assert not any("(25)" in ev["text"] for ev in events)

    run("fix lightning")
    events = ctx["feedback_bus"].drain()
    assert any("already at full charge" in ev["text"] for ev in events)
