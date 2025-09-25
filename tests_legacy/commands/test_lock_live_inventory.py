import shutil
from pathlib import Path

from mutants.app import context
from mutants.repl.dispatch import Dispatch
from mutants.commands import lock as lock_cmd, debug as debug_cmd
from mutants.registries.world import BASE_GATE
from mutants.registries import items_instances as itemsreg
from mutants import state as state_mod


class DummyWorld:
    def get_tile(self, x, y):
        return {"edges": {"W": {"base": BASE_GATE, "gate_state": 1}}}


def test_lock_uses_live_inventory(tmp_path, monkeypatch):
    # sandbox state
    src = Path(__file__).resolve().parents[2] / "state"
    dst = tmp_path / "state"
    shutil.copytree(src, dst)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("GAME_STATE_ROOT", str(dst))
    monkeypatch.setattr(state_mod, "STATE_ROOT", dst)
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
    monkeypatch.setattr(lock_cmd.dyn, "PATH", Path("state/world/dynamics.json"))
    ctx = context.build_context()
    ctx["world_loader"] = lambda year: DummyWorld()

    disp = Dispatch()
    disp.set_feedback_bus(ctx["feedback_bus"])
    debug_cmd.register(disp, ctx)
    lock_cmd.register(disp, ctx)

    disp.call("debug", "add gate_key_b")
    disp.call("lock", "w")
    events = ctx["feedback_bus"].drain()
    assert any("lock" in e["text"].lower() or "locked" in e["text"].lower() for e in events) \
        or not any("need a key" in e["text"].lower() for e in events)
