import types
from src.mutants.commands import throw as throw_cmd


class FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, text, **_):
        self.events.append((kind, text))

    def drain(self):
        ev, self.events = self.events, []
        return ev


def _ctx():
    return {"feedback_bus": FakeBus(), "player_state": {"pos": (2000, 5, 5)}}


def test_throw_usage_when_missing_args():
    ctx = _ctx()
    throw_cmd.throw_cmd("north", ctx)
    assert ctx["feedback_bus"].events == [("SYSTEM/WARN", "Type THROW [direction] [item].")]


def test_throw_invalid_direction_warns():
    ctx = _ctx()
    orig = throw_cmd.itx.throw_to_neighbor
    try:
        throw_cmd.itx.throw_to_neighbor = lambda *a, **k: {"ok": False, "reason": "invalid_direction"}
        throw_cmd.throw_cmd("up skull", ctx)
        assert ("SYSTEM/WARN", "That isn't a valid direction.") in ctx["feedback_bus"].events
    finally:
        throw_cmd.itx.throw_to_neighbor = orig


def test_throw_not_carrying_warns(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(
        throw_cmd.itx,
        "throw_to_neighbor",
        lambda ctx, dir, prefix: {"ok": False, "reason": "not_found"},
    )
    throw_cmd.throw_cmd("n skull", ctx)
    assert ("SYSTEM/WARN", "You're not carrying a skull.") in ctx["feedback_bus"].events


def test_throw_success_feedback(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(
        throw_cmd.itx, "throw_to_neighbor", lambda ctx, dir, prefix: {"ok": True}
    )
    throw_cmd.throw_cmd("north skull", ctx)
    assert ("COMBAT/THROW", "You throw the skull north.") in ctx["feedback_bus"].events
    assert ctx.get("render_next") is not True

