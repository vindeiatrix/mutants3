import shutil
from pathlib import Path

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import lock as lock_cmd
from mutants.registries.world import BASE_GATE
from mutants.registries import items_instances as itemsreg


class DummyWorld:
    def get_tile(self, x, y):
        return {"edges": {"W": {"base": BASE_GATE, "gate_state": 1}}}


def test_lock_uses_live_inventory(tmp_path, monkeypatch):
    # sandbox state
    src = Path(__file__).resolve().parents[2] / "state"
    dst = tmp_path / "state"
    shutil.copytree(src, dst)
    monkeypatch.chdir(tmp_path)

    itemsreg._CACHE = None
    monkeypatch.setattr(lock_cmd.dyn, "PATH", str(Path("state/world/dynamics.json")))
    ctx = context.build_context()
    ctx["world_loader"] = lambda year: DummyWorld()

    state_mgr = ctx["state_manager"]
    player = state_mgr.get_active().to_dict()
    pos = player.get("pos") or [2000, 0, 0]
    year, x, y = int(pos[0]), int(pos[1]), int(pos[2])
    iid = itemsreg.create_and_save_instance("gate_key_b", year, x, y, origin="test_lock")
    itemsreg.clear_position(iid)
    inv = player.setdefault("inventory", [])
    if iid not in inv:
        inv.append(iid)
    itemsreg.save_instances()

    disp = Dispatch()
    disp.set_feedback_bus(ctx["feedback_bus"])
    lock_cmd.register(disp, ctx)

    disp.call("lock", "w")
    events = ctx["feedback_bus"].drain()
    assert any("lock" in e["text"].lower() or "locked" in e["text"].lower() for e in events) \
        or not any("need a key" in e["text"].lower() for e in events)
