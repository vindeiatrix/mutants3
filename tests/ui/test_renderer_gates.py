import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mutants.ui import renderer
from mutants.app import context as appctx


def make_vm(edge_base, gate_state=0):
    return {
        "header": "",
        "coords": {"x": 0, "y": 0},
        "dirs": {"N": {"base": edge_base, "gate_state": gate_state}},
        "monsters_here": [],
        "ground_item_ids": [],
        "has_ground": False,
        "events": [],
        "shadows": [],
    }


class DummyResolver:
    def __init__(self, passable=True):
        self.passable = passable

    def resolve(self, *args, **kwargs):
        return types.SimpleNamespace(passable=self.passable, cur_raw=None, nbr_raw=None)


def _patch_ctx(monkeypatch):
    class P:
        year = 0
        x = 0
        y = 0

    ctx = {"player_state": P(), "world": object(), "dynamics": None}
    monkeypatch.setattr(appctx, "current_context", lambda: ctx)


def test_open_gate_is_rendered(monkeypatch):
    vm = make_vm(3, 0)
    monkeypatch.setattr(renderer, "ER", DummyResolver(passable=True))
    _patch_ctx(monkeypatch)
    out = renderer.token_debug_lines(vm)
    assert any("open gate" in line for line in out)


def test_closed_gate_is_rendered(monkeypatch):
    vm = make_vm(3, 0)
    monkeypatch.setattr(renderer, "ER", DummyResolver(passable=False))
    _patch_ctx(monkeypatch)
    out = renderer.token_debug_lines(vm)
    assert any("closed gate" in line or "locked gate" in line for line in out)


def test_plain_open_dropped_when_blocked(monkeypatch):
    vm = make_vm(0, 0)
    monkeypatch.setattr(renderer, "ER", DummyResolver(passable=False))
    _patch_ctx(monkeypatch)
    out = renderer.token_debug_lines(vm)
    assert not any("area continues" in line for line in out)
