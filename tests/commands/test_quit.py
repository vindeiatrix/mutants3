from mutants.commands import quit as quit_cmd
from mutants.repl.dispatch import Dispatch


class DummyStateManager:
    def __init__(self) -> None:
        self.saved = 0

    def save_on_exit(self) -> None:
        self.saved += 1

    def on_command_executed(self, executed):
        pass


class DummyBus:
    def __init__(self) -> None:
        self.events = []

    def push(self, kind, text):
        self.events.append((kind, text))


def make_ctx():
    bus = DummyBus()
    state_mgr = DummyStateManager()
    ctx = {"feedback_bus": bus, "state_manager": state_mgr}
    return ctx, bus, state_mgr


def register_quit(ctx):
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    quit_cmd.register(dispatch, ctx)
    return dispatch


def test_quit_prefix_saves_and_notifies():
    ctx, bus, state_mgr = make_ctx()
    dispatch = register_quit(ctx)

    executed = dispatch.call("qui", "")

    assert executed == "quit"
    assert state_mgr.saved == 1
    assert ("SYSTEM/OK", "Goodbye!") in bus.events


def test_quit_alias_q():
    ctx, bus, state_mgr = make_ctx()
    dispatch = register_quit(ctx)

    executed = dispatch.call("q", "")

    assert executed == "quit"
    assert state_mgr.saved == 1
    assert ("SYSTEM/OK", "Goodbye!") in bus.events
