import shutil
from pathlib import Path

import pytest

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import debug
from mutants.registries import items_instances as itemsreg, items_catalog
from mutants.services import item_transfer as it


@pytest.fixture
def ctx_with_player(monkeypatch, tmp_path):
    src_state = Path(__file__).resolve().parents[1] / "state"
    dst_state = tmp_path / "state"
    shutil.copytree(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    itemsreg._CACHE = None
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
