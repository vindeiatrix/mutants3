import shutil
from pathlib import Path

import pytest

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import debug, inv, look, point, fix
from mutants.registries import items_instances as itemsreg
from mutants.commands._helpers import inventory_iids_for_active_player


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    shutil.copytree(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    itemsreg._CACHE = None
    # Clear positions to simplify
    for inst in itemsreg.list_instances_at(2000, 0, 0):
        iid = inst.get("iid") or inst.get("instance_id")
        if iid:
            itemsreg.clear_position(iid)
    itemsreg.save_instances()
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
    assert any("Lightning" in ev["text"] and "(25)" in ev["text"] for ev in events)

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
    assert any("Lightning" in ev["text"] and "(25)" in ev["text"] for ev in events)

    run("fix lightning")
    events = ctx["feedback_bus"].drain()
    assert any("already at full charge" in ev["text"] for ev in events)
