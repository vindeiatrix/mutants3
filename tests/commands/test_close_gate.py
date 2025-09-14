import types

from mutants.commands import close as close_cmd
from mutants.repl.dispatch import Dispatch
from mutants.registries.world import BASE_GATE


class DummyWorld:
    def __init__(self, edge):
        self._edge = edge
        self.saved = False

    def get_tile(self, x, y):
        return {"edges": {"W": self._edge}}

    def set_edge(self, x, y, D, *, gate_state=None, force_gate_base=False):
        if force_gate_base:
            self._edge["base"] = BASE_GATE
        if gate_state is not None:
            self._edge["gate_state"] = gate_state

    def save(self):
        self.saved = True


def mk_ctx(edge):
    bus = types.SimpleNamespace(msgs=[])

    def push(chan, msg):
        bus.msgs.append((chan, msg))

    bus.push = push
    world = DummyWorld(edge)
    ctx = {
        "feedback_bus": bus,
        "player_state": {
            "active_id": 1,
            "players": [{"id": 1, "pos": [2000, 0, 0]}],
        },
        "world_loader": lambda year: world,
    }
    return world, ctx, bus


def run_close(ctx, arg):
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    close_cmd.register(dispatch, ctx)
    dispatch.call("close", arg)


def test_close_on_open_gate_sets_closed():
    edge = {"base": BASE_GATE, "gate_state": 0}
    world, ctx, bus = mk_ctx(edge)
    run_close(ctx, "west")
    assert edge["gate_state"] == 1
    assert world.saved is True
    assert ("SYSTEM/OK", "You've just closed the west gate.") in bus.msgs


def test_close_on_already_closed_gate_informs():
    edge = {"base": BASE_GATE, "gate_state": 1}
    world, ctx, bus = mk_ctx(edge)
    run_close(ctx, "west")
    assert edge["gate_state"] == 1
    assert world.saved is False
    assert ("SYSTEM/INFO", "The west gate is already closed.") in bus.msgs


def test_close_when_no_gate_warns():
    edge = {"base": 0, "gate_state": 0}
    world, ctx, bus = mk_ctx(edge)
    run_close(ctx, "west")
    assert world.saved is False
    assert ("SYSTEM/WARN", "There is no gate to close that way.") in bus.msgs


def test_close_accepts_prefix():
    edge = {"base": BASE_GATE, "gate_state": 0}
    world, ctx, bus = mk_ctx(edge)
    run_close(ctx, "we")
    assert edge["gate_state"] == 1
    assert ("SYSTEM/OK", "You've just closed the west gate.") in bus.msgs
